"""Worker의 Ready Queue 핵심 자료구조를 제공한다."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, replace
from threading import RLock


MAX_QUEUE_SIZE = 10


def _validate_transfer_id(transfer_id: str) -> None:
    """전송 예약 식별자가 비어 있지 않은 문자열인지 확인한다."""
    if not isinstance(transfer_id, str):
        raise TypeError("transfer_id는 문자열이어야 합니다.")
    if not transfer_id.strip():
        raise ValueError("transfer_id는 비어 있지 않은 문자열이어야 합니다.")


def _validate_count(count: int) -> None:
    """작업 개수가 1 이상의 정수인지 확인한다."""
    if isinstance(count, bool) or not isinstance(count, int):
        raise TypeError("count는 bool이 아닌 정수여야 합니다.")
    if count < 1:
        raise ValueError("count는 1 이상이어야 합니다.")


@dataclass(frozen=True)
class WorkerTask:
    """Worker의 Ready Queue에 저장되는 작업 하나를 나타낸다.

    객체를 고정된 dataclass로 만들어, Queue 밖에서 작업의 예약 상태를
    임의로 변경하지 못하게 한다.
    """

    key: str
    value: int
    attempt: int
    enqueued_at: float
    reserved_transfer_id: str | None = None

    def __post_init__(self) -> None:
        """작업 입력값을 검증하고 key를 대문자로 정규화한다."""
        if not isinstance(self.key, str):
            raise TypeError("key는 문자열이어야 합니다.")
        if len(self.key) != 4 or any(
            character not in "0123456789abcdefABCDEF" for character in self.key
        ):
            raise ValueError("key는 정확히 4자리 16진수 문자열이어야 합니다.")

        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError("value는 bool이 아닌 정수여야 합니다.")
        if not 1 <= self.value <= 100:
            raise ValueError("value는 1 이상 100 이하여야 합니다.")

        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int):
            raise TypeError("attempt는 bool이 아닌 정수여야 합니다.")
        if self.attempt < 1:
            raise ValueError("attempt는 1 이상이어야 합니다.")

        if isinstance(self.enqueued_at, bool) or not isinstance(
            self.enqueued_at, (int, float)
        ):
            raise TypeError("enqueued_at은 숫자여야 합니다.")
        if not math.isfinite(self.enqueued_at):
            raise ValueError("enqueued_at은 유한한 숫자여야 합니다.")

        if self.reserved_transfer_id is not None:
            _validate_transfer_id(self.reserved_transfer_id)

        object.__setattr__(self, "key", self.key.upper())
        object.__setattr__(self, "enqueued_at", float(self.enqueued_at))


class WorkerReadyQueue:
    """Worker가 처리하기 전 작업을 보관하는 thread-safe Ready Queue."""

    def __init__(self, max_size: int = MAX_QUEUE_SIZE) -> None:
        """최대 크기가 1 이상 10 이하인 빈 Queue를 만든다."""
        if isinstance(max_size, bool) or not isinstance(max_size, int):
            raise TypeError("max_size는 bool이 아닌 정수여야 합니다.")
        if not 1 <= max_size <= MAX_QUEUE_SIZE:
            raise ValueError("max_size는 1 이상 10 이하여야 합니다.")

        self._queue: deque[WorkerTask] = deque()
        self._max_size = max_size
        self._lock = RLock()

    def get_queue_size(self) -> int:
        """예약된 작업을 포함한 현재 대기 작업 수를 반환한다."""
        with self._lock:
            return len(self._queue)

    def has_capacity(self, count: int = 1) -> bool:
        """count개의 작업을 추가할 공간이 있는지 확인한다."""
        _validate_count(count)

        with self._lock:
            return len(self._queue) + count <= self._max_size

    def enqueue(self, task: WorkerTask) -> bool:
        """공간이 있으면 작업을 Queue 뒤에 넣고 True를 반환한다."""
        if not isinstance(task, WorkerTask):
            raise TypeError("task는 WorkerTask 객체여야 합니다.")

        # 크기 확인과 추가를 같은 잠금 안에서 처리해야 동시에 초과 삽입되지 않는다.
        with self._lock:
            if len(self._queue) >= self._max_size:
                return False

            self._queue.append(task)
            return True

    def dequeue(self) -> WorkerTask | None:
        """예약되지 않은 가장 앞 작업을 제거하여 반환한다.

        예약된 작업은 Queue 크기에는 포함되지만 일반 처리 대상으로는
        꺼내지 않는다. 처리할 수 있는 작업이 없으면 None을 반환한다.
        """
        with self._lock:
            for index, task in enumerate(self._queue):
                if task.reserved_transfer_id is None:
                    del self._queue[index]
                    return task

            return None

    def reserve_for_transfer(
        self, transfer_id: str, count: int
    ) -> list[WorkerTask]:
        """Queue 뒤쪽부터 예약되지 않은 작업을 최대 count개 예약한다.

        같은 transfer_id로 이미 예약한 작업이 있으면 새로 예약하지 않고
        기존 예약 목록을 반환한다.
        반환 목록은 Queue 뒤에서부터 선택한 순서로 정렬된다.
        """
        _validate_transfer_id(transfer_id)
        _validate_count(count)

        reserved_tasks: list[WorkerTask] = []

        # 탐색과 예약 표시를 한 잠금 안에서 수행해 중복 예약을 막는다.
        with self._lock:
            # 최초 호출과 같은 순서를 유지하기 위해 뒤쪽부터 기존 예약을 찾는다.
            for index in range(len(self._queue) - 1, -1, -1):
                task = self._queue[index]
                if task.reserved_transfer_id == transfer_id:
                    reserved_tasks.append(task)

            if reserved_tasks:
                return reserved_tasks

            for index in range(len(self._queue) - 1, -1, -1):
                task = self._queue[index]
                if task.reserved_transfer_id is not None:
                    continue

                reserved_task = replace(task, reserved_transfer_id=transfer_id)
                self._queue[index] = reserved_task
                reserved_tasks.append(reserved_task)

                if len(reserved_tasks) == count:
                    break

        return reserved_tasks

    def confirm_transfer(self, transfer_id: str) -> list[WorkerTask]:
        """해당 전송 ID로 예약된 작업을 Queue에서 제거하여 반환한다."""
        _validate_transfer_id(transfer_id)

        removed_tasks: list[WorkerTask] = []

        # 원래 Queue 순서를 유지하면서 예약이 일치하지 않는 작업만 남긴다.
        with self._lock:
            remaining_tasks: deque[WorkerTask] = deque()

            for task in self._queue:
                if task.reserved_transfer_id == transfer_id:
                    removed_tasks.append(task)
                else:
                    remaining_tasks.append(task)

            self._queue = remaining_tasks

        return removed_tasks

    def cancel_transfer(self, transfer_id: str) -> int:
        """해당 전송 ID의 예약을 해제하고 해제한 작업 수를 반환한다."""
        _validate_transfer_id(transfer_id)

        canceled_count = 0

        with self._lock:
            for index, task in enumerate(self._queue):
                if task.reserved_transfer_id == transfer_id:
                    self._queue[index] = replace(task, reserved_transfer_id=None)
                    canceled_count += 1

        return canceled_count

    def snapshot(self) -> list[WorkerTask]:
        """현재 Queue 내용을 내부 deque와 분리된 목록으로 반환한다."""
        with self._lock:
            return list(self._queue)


class WorkerStorage:
    """Worker가 성공적으로 처리한 Key-Value를 보관한다."""

    def __init__(self) -> None:
        """빈 Key-Value 저장소를 만든다."""
        self._storage: dict[str, int] = {}
        self._lock = RLock()

    def store(self, task: WorkerTask) -> bool:
        """새 작업 결과를 저장하고, 이미 저장된 결과이면 False를 반환한다."""
        if not isinstance(task, WorkerTask):
            raise TypeError("task는 WorkerTask 객체여야 합니다.")

        # 확인과 저장을 같은 잠금 안에서 처리해 중복 저장을 막는다.
        with self._lock:
            if task.key not in self._storage:
                self._storage[task.key] = task.value
                return True

            if self._storage[task.key] == task.value:
                return False

            raise ValueError("같은 key에 다른 value가 이미 저장되어 있습니다.")

    def get_value(self, key: str) -> int | None:
        """Key에 저장된 Value를 반환하고, 없으면 None을 반환한다."""
        if not isinstance(key, str):
            raise TypeError("key는 문자열이어야 합니다.")
        if len(key) != 4 or any(
            character not in "0123456789abcdefABCDEF" for character in key
        ):
            raise ValueError("key는 정확히 4자리 16진수 문자열이어야 합니다.")

        normalized_key = key.upper()

        with self._lock:
            return self._storage.get(normalized_key)

    def get_storage_size(self) -> int:
        """저장된 고유 Key 개수를 반환한다."""
        with self._lock:
            return len(self._storage)

    def snapshot(self) -> dict[str, int]:
        """현재 저장 내용을 내부 dict와 분리된 복사본으로 반환한다."""
        with self._lock:
            return self._storage.copy()
