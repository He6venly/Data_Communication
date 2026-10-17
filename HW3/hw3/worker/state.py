# Worker 상태·작업 Queue·Checkpoint Store를 관리한다.

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class Assignment:
    task: int
    epoch: int
    from_worker: int | None = None


@dataclass(frozen=True, order=True)
class Checkpoint:
    epoch: int
    step: int
    partial: int


@dataclass(frozen=True)
class Work:
    assignment: Assignment
    generation: int
    resume_step: int
    partial: int
    ckpt_epoch: int | None


class WorkerState:
    def __init__(self):
        self.queue_lock = threading.RLock()
        self.state_lock = threading.Lock()
        self.store_lock = threading.Lock()
        self.cv = threading.Condition(self.queue_lock)
        self.queue: deque[Assignment] = deque()
        self.store: dict[int, Checkpoint] = {}
        self.latest: dict[int, int] = {}
        self.sent_epochs: dict[int, set[int]] = {}
        self.mode = "BOOTING"
        self.crash_gen = 0
        self.crash_count = 0
        self.rejoin_count = 0
        self.current: Work | None = None
        self.requested = False
        self.no_task = False
        self.started = False
        self.launcher_connected = False
        self.ready_sent = False
        self.rejoin_due: float | None = None
        self.stop_event = threading.Event()

    @contextmanager
    def locked(self):
        with self.queue_lock, self.state_lock, self.store_lock:
            yield

    def active(self, generation: int, assignment: Assignment | None = None) -> bool:
        return (self.mode == "RUNNING" and self.crash_gen == generation
                and (assignment is None or self.latest.get(assignment.task) == assignment.epoch))

    def start(self) -> bool:
        with self.locked():
            if self.mode != "BOOTING":
                return False
            self.started = True
            self.mode = "RUNNING"
            self.cv.notify_all()
            return True

    def enqueue(self, assignment: Assignment, generation: int | None = None) -> bool:
        with self.locked():
            accepting = (self.mode == "RUNNING"
                         or (self.mode == "REJOINING" and assignment.from_worker is not None))
            if not accepting or (generation is not None and generation != self.crash_gen):
                return False
            if assignment.from_worker is None:
                self.requested = False
            if assignment.epoch <= self.latest.get(assignment.task, 0):
                return False
            self.latest[assignment.task] = assignment.epoch
            self.queue = deque(a for a in self.queue if a.task != assignment.task)
            self.queue.append(assignment)
            self.cv.notify_all()
            return True

    def needs_request(self) -> bool:
        return (self.mode == "RUNNING" and self.current is None and not self.queue
                and not self.requested and not self.no_task)

    def save_checkpoint(self, task: int, checkpoint: Checkpoint) -> bool:
        with self.locked():
            if self.mode not in {"BOOTING", "RUNNING", "REJOINING"}:
                return False
            old = self.store.get(task)
            if old is not None and (checkpoint.epoch, checkpoint.step) <= (old.epoch, old.step):
                return False
            self.store[task] = checkpoint
            return True

    def take_work(self) -> Work | None:
        with self.cv:
            while True:
                with self.state_lock, self.store_lock:
                    if self.mode == "STOPPED":
                        return None
                    if self.mode == "RUNNING" and self.queue:
                        assignment = self.queue.popleft()
                        ckpt = self.store.get(assignment.task) if assignment.from_worker is not None else None
                        if ckpt is not None and ckpt.epoch >= assignment.epoch:
                            ckpt = None
                        work = Work(assignment, self.crash_gen,
                                    ckpt.step + 1 if ckpt else 1,
                                    ckpt.partial if ckpt else 0,
                                    ckpt.epoch if ckpt else None)
                        self.current = work
                        return work
                self.cv.wait()

    def valid(self, work: Work) -> bool:
        with self.locked():
            return self.current is work and self.active(work.generation, work.assignment)

    def delay(self, work: Work, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        with self.cv:
            while True:
                with self.state_lock, self.store_lock:
                    if self.current is not work or not self.active(work.generation, work.assignment):
                        return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return True
                self.cv.wait(remaining)

    def finish(self, work: Work):
        with self.locked():
            if self.current is work:
                self.current = None
                self.cv.notify_all()

    def mark_no_task(self, generation: int | None = None):
        with self.locked():
            if self.mode == "RUNNING" and (generation is None or generation == self.crash_gen):
                self.requested = False
                self.no_task = True
                self.cv.notify_all()
                return True
            return False

    def crash(self) -> dict | None:
        with self.locked():
            if self.mode != "RUNNING":
                return None
            cleared = {"queue_cleared": len(self.queue), "store_cleared": len(self.store),
                       "current_task": self.current.assignment.task if self.current else None}
            self.mode = "CRASHED"
            self.crash_gen += 1
            self.crash_count += 1
            self.queue.clear()
            self.store.clear()
            self.latest.clear()
            self.sent_epochs.clear()
            self.current = None
            self.requested = False
            self.no_task = False
            self.rejoin_due = None
            self.cv.notify_all()
            return {**cleared, "crash_gen": self.crash_gen, "crash_count": self.crash_count}

    def restart(self) -> bool:
        with self.locked():
            if self.mode != "CRASHED":
                return False
            self.mode = "REJOINING"
            self.rejoin_due = time.monotonic()
            self.cv.notify_all()
            return True

    def retry_later(self):
        with self.locked():
            if self.mode == "REJOINING":
                self.rejoin_due = time.monotonic() + 2.0
                self.cv.notify_all()
                return True
            return False

    def welcome(self) -> bool:
        with self.locked():
            if self.mode != "REJOINING":
                return False
            self.mode = "RUNNING"
            self.rejoin_count += 1
            self.rejoin_due = None
            self.cv.notify_all()
            return True

    def stop(self):
        with self.locked():
            self.mode = "STOPPED"
            self.stop_event.set()
            self.cv.notify_all()
