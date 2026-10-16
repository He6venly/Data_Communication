"""No I/O here. Nested locks: Worker Table -> one Task -> done condition.

RESULT releases the Worker lock before taking its Task lock, as in the spec.
An event's seq/elapsed_ms describe the decision, not a delayed file write.
"""

from collections import deque
from dataclasses import dataclass, field
import threading
import time

from hw3.common.settings import (
    TASK_COUNT, WORKER_COUNT, SUSPECT_TIMEOUT_SECONDS, DEAD_TIMEOUT_SECONDS,
    EXPECTED_PRIME_COUNT,
)


@dataclass
class Task:
    state: str = "PENDING"
    owner: int | None = None
    epoch: int = 0
    result: int | None = None
    commit_count: int = 0
    committed_at: float | None = None
    lock: object = field(default_factory=threading.Lock, repr=False)


@dataclass
class Worker:
    channel: object = None
    peer: tuple[str, int] | None = None
    ring_ok: bool = False
    state: str = "ALIVE"
    last_hb: float = 0.0
    rejoin_count: int = 0
    crash_count: int = 0
    rejoin_record: dict | None = None


@dataclass(frozen=True)
class Event:
    kind: str
    status: str
    fields: dict


class Tables:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.ready = threading.Condition(self.lock)
        self.done = threading.Condition()
        self.event_lock = threading.Lock()
        self.sequence = 0
        self.tasks = [Task() for _ in range(TASK_COUNT)]
        self.workers = {i: Worker() for i in range(1, WORKER_COUNT + 1)}
        self.pending = deque(range(TASK_COUNT))
        self.done_count = 0
        self.phase = "REGISTERING"
        self.started_at = None
        self.detector_enabled = False
        self.faults = []
        self.rejoins = []

    def event(self, kind, status="INFO", *, now=None, **fields):
        now = self.clock() if now is None else now
        with self.event_lock:
            self.sequence += 1
            seq = self.sequence
        elapsed = None if self.started_at is None else (now - self.started_at) * 1000
        return Event(kind, status, {"seq": seq, "elapsed_ms": elapsed, **fields})

    def hello(self, channel, worker_id, ip, port):
        with self.ready:
            worker = self.workers[worker_id]
            if self.phase != "REGISTERING" or worker.channel is not None or channel.worker_id is not None:
                return [self.event("PROTOCOL", "WARN", message="duplicate/late HELLO", worker=worker_id)]
            worker.channel, worker.peer = channel, (ip, port)
            channel.worker_id = worker_id
            self.ready.notify_all()
            return [self.event("HELLO", worker=worker_id, ip=ip, port=port,
                               registered=sum(w.channel is not None for w in self.workers.values()))]

    def ring_ok(self, worker_id):
        with self.ready:
            if self.phase != "RING":
                return [self.event("PROTOCOL", "WARN", worker=worker_id, message="unexpected RING_OK")]
            self.workers[worker_id].ring_ok = True
            self.ready.notify_all()
            return [self.event("RING_OK", worker=worker_id,
                               ring_ready=sum(w.ring_ok for w in self.workers.values()))]

    def begin(self):
        with self.lock:
            if not all(w.ring_ok for w in self.workers.values()):
                raise RuntimeError("START before ten RING_OK messages")
            now = self.clock()
            self.started_at, self.phase = now, "RUNNING"
            for worker in self.workers.values():
                worker.last_hb = now
            return self.event("START", "SUCCESS", now=now, ring_ready=WORKER_COUNT)

    def heartbeat(self, worker_id):
        with self.lock:
            worker = self.workers[worker_id]
            if self.phase != "RUNNING" or worker.state == "DEAD":
                return []
            now = self.clock()
            recovered = worker.state == "SUSPECT"
            worker.last_hb, worker.state = now, "ALIVE"
            events = [self.event("HB", now=now, worker=worker_id)]
            if recovered:
                events.append(self.event("ALIVE", now=now, worker=worker_id, reason="HB"))
            return events

    def request(self, worker_id):
        with self.lock:
            worker = self.workers[worker_id]
            if self.phase != "RUNNING" or worker.state == "DEAD":
                return None, [self.event("REQ", "WARN", worker=worker_id, reason="not assignable")]
            if not self.pending:
                return ("NO_TASK", ()), [self.event("NO_TASK", worker=worker_id, pending=0,
                                                   rejoin_count=worker.rejoin_count)]
            k = self.pending.popleft()
            with self.tasks[k].lock:
                task = self.tasks[k]
                task.state, task.owner, task.epoch = "ASSIGNED", worker_id, 1
            now = self.clock()
            record = worker.rejoin_record
            if record is not None and record["first_assign"] is None:
                record["first_assign"], record["first_task"] = now, k
            return ("ASSIGN", (k, 1)), [self.event("ASSIGN", now=now, task=k, epoch=1,
                                                 worker=worker_id, rejoin_count=worker.rejoin_count)]

    def result(self, worker_id, k, epoch, value):
        with self.lock:
            worker = self.workers[worker_id]
            dead = worker.state == "DEAD"
            rejoin_count, record = worker.rejoin_count, worker.rejoin_record
        events = []
        with self.tasks[k].lock:
            task = self.tasks[k]
            fields = {"task": k, "epoch": epoch, "worker": worker_id, "result": value}
            events.append(self.event("RESULT", **fields))
            reason = ("DEAD" if dead else "DONE" if task.state == "DONE" else
                      "EPOCH" if task.epoch != epoch or task.owner != worker_id else None)
            if reason is not None:
                events.append(self.event("REJECT_STALE", "WARN", reason=reason, **fields))
                return ("REJECT_STALE", (k, reason)), events
            now = self.clock()
            task.state, task.result, task.committed_at = "DONE", value, now
            task.commit_count += 1
            events.append(self.event("COMMIT", "SUCCESS", now=now, commit_count=task.commit_count,
                                     rejoin_count=rejoin_count, **fields))
            with self.done:
                if record is not None:
                    record["commits"] += 1
                self.done_count += 1
                self.done.notify_all()
            return ("ACK", (k,)), events

    def rejoin(self, worker_id):
        with self.lock:
            worker = self.workers[worker_id]
            if self.phase != "RUNNING" or worker.state != "DEAD":
                return ("RETRY_LATER", ()), [self.event("RETRY_LATER", worker=worker_id)]
            now = self.clock()
            worker.state, worker.last_hb = "ALIVE", now
            worker.rejoin_count += 1
            record = {"worker": worker_id, "rejoin_count": worker.rejoin_count, "time": now,
                      "first_assign": None, "first_task": None, "commits": 0}
            worker.rejoin_record = record
            self.rejoins.append(record)
            return ("WELCOME", ()), [self.event("REJOIN", "SUCCESS", now=now, worker=worker_id,
                                                rejoin_count=worker.rejoin_count, pending=len(self.pending)),
                                      self.event("WELCOME", now=now, worker=worker_id,
                                                 rejoin_count=worker.rejoin_count)]

    def next_alive(self, source):
        order = [(source + offset - 1) % WORKER_COUNT + 1 for offset in range(1, WORKER_COUNT)]
        for state in ("ALIVE", "SUSPECT"):
            for worker_id in order:
                if self.workers[worker_id].state == state:
                    return worker_id
        raise RuntimeError("no live or suspect takeover target")

    def detect(self):
        events, actions = [], []
        with self.lock:
            if not self.detector_enabled or self.phase != "RUNNING":
                return events, actions
            now = self.clock()
            newly_dead = []
            for worker_id, worker in self.workers.items():
                if worker.state == "DEAD":
                    continue
                gap = now - worker.last_hb
                if gap >= DEAD_TIMEOUT_SECONDS:
                    newly_dead.append(worker_id)
                elif gap >= SUSPECT_TIMEOUT_SECONDS and worker.state != "SUSPECT":
                    worker.state = "SUSPECT"
                    events.append(self.event("SUSPECT", now=now, worker=worker_id,
                                             last_hb_elapsed_ms=(worker.last_hb-self.started_at)*1000,
                                             detection_delay_ms=gap*1000))
            for worker_id in newly_dead:
                self.workers[worker_id].state = "DEAD"
            dead_now = [i for i, w in self.workers.items() if w.state == "DEAD"]
            for source in newly_dead:  # dict insertion order is worker number order.
                worker = self.workers[source]
                target = self.next_alive(source)
                worker.crash_count += 1
                owned = []
                event = self.event("DEAD", now=now, worker=source, crash_count=worker.crash_count,
                                   last_hb_elapsed_ms=(worker.last_hb-self.started_at)*1000,
                                   detection_delay_ms=(now-worker.last_hb)*1000,
                                   owned_tasks=owned, to_worker=target, dead_now=dead_now)
                events.append(event)
                for k, task in enumerate(self.tasks):
                    with task.lock:
                        if task.state != "ASSIGNED" or task.owner != source:
                            continue
                        old_epoch = task.epoch
                        task.epoch += 1
                        task.owner = target
                        owned.append(k)
                        events.append(self.event("TAKEOVER", "SUCCESS", now=now, task=k,
                                                 old_epoch=old_epoch, epoch=task.epoch,
                                                 from_worker=source, to_worker=target))
                        actions.append((target, "TAKEOVER", (k, task.epoch, f"from={source}")))
                events.append(self.event("DEAD_SCAN", now=now, worker=source,
                                         crash_count=worker.crash_count, owned_tasks=list(owned)))
                self.faults.append({"worker": source, "crash_count": worker.crash_count,
                                    "time": now, "last_hb": worker.last_hb,
                                    "tasks": tuple(owned), "to_worker": target})
        return events, actions

    def snapshot(self):
        counts = {"PENDING": 0, "ASSIGNED": 0, "DONE": 0}
        commits, results = [], []
        for task in self.tasks:
            with task.lock:
                counts[task.state] += 1
                commits.append(task.commit_count)
                results.append(task.result or 0)
        with self.lock:
            alive_workers = [i for i, w in self.workers.items() if w.state == "ALIVE"]
            suspect_workers = [i for i, w in self.workers.items() if w.state == "SUSPECT"]
            dead_workers = [i for i, w in self.workers.items() if w.state == "DEAD"]
        return {"pending": counts["PENDING"], "assigned": counts["ASSIGNED"], "done": counts["DONE"],
                "alive": len(alive_workers), "alive_workers": alive_workers,
                "suspect_workers": suspect_workers, "dead_workers": dead_workers,
                "commits": sum(commits), "double_commit": sum(c > 1 for c in commits),
                "sum": sum(results), "all_commit_once": all(c == 1 for c in commits),
                "min_commit_count": min(commits), "max_commit_count": max(commits)}

    def verify(self):
        summary = self.snapshot()
        summary["pass"] = (summary["done"] == TASK_COUNT and summary["all_commit_once"]
                           and summary["sum"] == EXPECTED_PRIME_COUNT)
        return summary

    def metrics(self):
        with self.lock:
            faults = [dict(f) for f in self.faults]
            rejoins = [dict(r) for r in self.rejoins]
        commit_times = []
        for task in self.tasks:
            with task.lock:
                commit_times.append(task.committed_at)
        elapsed = (max(t for t in commit_times if t is not None) - self.started_at)
        for fault in faults:
            fault["owned_tasks"] = list(fault["tasks"])
            fault["last_hb_elapsed_ms"] = (fault["last_hb"]-self.started_at)*1000
            fault["dead_elapsed_ms"] = (fault["time"]-self.started_at)*1000
            times = [commit_times[k] for k in fault.pop("tasks")]
            fault["detection_ms"] = (fault["time"] - fault.pop("last_hb")) * 1000
            fault["recovery_ms"] = (max(times) - fault["time"]) * 1000 if times else None
            fault.pop("time")
        for record in rejoins:
            first = record.pop("first_assign")
            record["latency_ms"] = None if first is None else (first-record["time"])*1000
            record.pop("time")
        return {"execution_ms": elapsed*1000, "throughput": TASK_COUNT/elapsed if elapsed else None,
                "faults": faults, "rejoins": rejoins}
