"""Deterministic state and timer rules for Chaos Launcher."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from hw3.common.settings import (
    CRASH_CUTOFF_SECONDS,
    CRASH_INTERVAL_SECONDS,
    DOWNTIME_SECONDS,
    INITIAL_CRASH_INTERVAL_SECONDS,
    WORKER_COUNT,
)
from hw3.common.transport import LineBuffer


class WorkerStatus(Enum):
    RUNNING = "RUNNING"
    CRASHED = "CRASHED"
    REJOINING = "REJOINING"
    EXITED = "EXITED"


@dataclass(slots=True)
class WorkerSlot:
    worker_id: int
    process: Any = None
    control_socket: Any = None
    line_buffer: LineBuffer = field(default_factory=LineBuffer)
    status: WorkerStatus = WorkerStatus.RUNNING
    restart_at: float | None = None
    crash_count: int = 0
    ready: bool = False


@dataclass(frozen=True, slots=True)
class CrashPlan:
    worker_id: int
    crash_count: int
    downtime: float
    restart_at: float
    candidates: tuple[int, ...]
    down: tuple[int, ...]


class ChaosController:
    """Own Launcher state while leaving socket I/O to the event loop."""

    def __init__(
        self,
        worker_count: int = WORKER_COUNT,
        seed: int | None = None,
        *,
        rng: Any = None,
        clock: Any = time.monotonic,
    ) -> None:
        if worker_count != WORKER_COUNT:
            raise ValueError(f"HW3 requires exactly {WORKER_COUNT} workers")
        self.workers = {i: WorkerSlot(i) for i in range(1, worker_count + 1)}
        self.rng = rng if rng is not None else random.Random(seed)
        self.clock = clock
        self.t0: float | None = None
        self.next_crash: float | None = None
        self.blocked = False
        self.injection_finished = False

    def mark_ready(self, worker_id: int, now: float | None = None) -> bool:
        slot = self._slot(worker_id)
        slot.ready = True
        if self.t0 is None and all(worker.ready for worker in self.workers.values()):
            current = self._now(now)
            self.t0 = current
            interval = self.rng.uniform(*INITIAL_CRASH_INTERVAL_SECONDS)
            self.next_crash = current + interval
            return True
        return False

    def due_crash(self, now: float | None = None) -> CrashPlan | None:
        current = self._now(now)
        if self.t0 is None or self.injection_finished:
            return None
        if current >= self.cutoff:
            self.finish_injection()
            return None
        if self.next_crash is None or current < self.next_crash or self.down_count >= 2:
            return None

        candidates = tuple(
            worker_id
            for worker_id, slot in self.workers.items()
            if slot.status is WorkerStatus.RUNNING
        )
        if not candidates:
            self.next_crash = None
            self.blocked = True
            return None

        # The random call order is part of the reproducible assignment contract.
        worker_id = self.rng.choice(candidates)
        downtime = self.rng.uniform(*DOWNTIME_SECONDS)
        slot = self.workers[worker_id]
        slot.status = WorkerStatus.CRASHED
        slot.crash_count += 1
        slot.restart_at = current + downtime

        if self.down_count >= 2:
            self.next_crash = None
            self.blocked = True
        else:
            self._schedule_next(current)

        return CrashPlan(
            worker_id=worker_id,
            crash_count=slot.crash_count,
            downtime=downtime,
            restart_at=slot.restart_at,
            candidates=candidates,
            down=self.down_workers,
        )

    def due_restarts(self, now: float | None = None) -> list[int]:
        current = self._now(now)
        due: list[int] = []
        for worker_id, slot in self.workers.items():
            if (
                slot.status is WorkerStatus.CRASHED
                and slot.restart_at is not None
                and current >= slot.restart_at
            ):
                slot.status = WorkerStatus.REJOINING
                slot.restart_at = None
                due.append(worker_id)
        return due

    def mark_rejoined(self, worker_id: int, now: float | None = None) -> bool:
        slot = self._slot(worker_id)
        if slot.status is not WorkerStatus.REJOINING:
            return False
        slot.status = WorkerStatus.RUNNING
        slot.restart_at = None
        if self.blocked and self.down_count < 2 and not self.injection_finished:
            self.blocked = False
            self._schedule_next(self._now(now))
        return True

    def mark_exited(self, worker_id: int) -> None:
        slot = self._slot(worker_id)
        slot.status = WorkerStatus.EXITED
        slot.restart_at = None

    def finish_if_cutoff(self, now: float | None = None) -> bool:
        if self.t0 is None or self.injection_finished:
            return False
        if self._now(now) < self.cutoff:
            return False
        self.finish_injection()
        return True

    def finish_injection(self) -> None:
        self.injection_finished = True
        self.next_crash = None
        self.blocked = False

    @property
    def cutoff(self) -> float:
        if self.t0 is None:
            raise RuntimeError("t0 has not been set")
        return self.t0 + CRASH_CUTOFF_SECONDS

    @property
    def ready_count(self) -> int:
        return sum(slot.ready for slot in self.workers.values())

    @property
    def down_workers(self) -> tuple[int, ...]:
        return tuple(
            worker_id
            for worker_id, slot in self.workers.items()
            if slot.status in {WorkerStatus.CRASHED, WorkerStatus.REJOINING}
        )

    @property
    def down_count(self) -> int:
        return len(self.down_workers)

    @property
    def all_exited(self) -> bool:
        return all(slot.status is WorkerStatus.EXITED for slot in self.workers.values())

    def next_deadline(self) -> float | None:
        deadlines = [
            slot.restart_at
            for slot in self.workers.values()
            if slot.status is WorkerStatus.CRASHED and slot.restart_at is not None
        ]
        if self.next_crash is not None:
            deadlines.append(self.next_crash)
        if self.t0 is not None and not self.injection_finished:
            deadlines.append(self.cutoff)
        return min(deadlines) if deadlines else None

    def _schedule_next(self, base: float) -> None:
        interval = self.rng.uniform(*CRASH_INTERVAL_SECONDS)
        candidate = base + interval
        if candidate >= self.cutoff:
            self.next_crash = None
        else:
            self.next_crash = candidate

    def _slot(self, worker_id: int) -> WorkerSlot:
        try:
            return self.workers[worker_id]
        except KeyError as error:
            raise ValueError(f"worker_id must be 1..{len(self.workers)}") from error

    def _now(self, now: float | None) -> float:
        return self.clock() if now is None else now
