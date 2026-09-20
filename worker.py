"""Worker의 자료구조, Master 연결, 작업 처리와 P2P 이전을 제공한다."""

from __future__ import annotations

import math
import random
import socket
from collections import deque
from dataclasses import dataclass, replace
from threading import Event, RLock, Thread

from logger import NodeLogger
from p2p import P2PNode, clean_tasks
from protocol import ConnectionClosed, InvalidMessage, JsonLineConnection


MAX_QUEUE_SIZE = 10


def _unique_communication_ids(message_ids: list[str]) -> list[str]:
    """처음 등장한 순서를 유지하면서 통신 ID의 중복을 제거한다."""
    result = []
    seen = set()
    for message_id in message_ids:
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError("communication_ids에는 비어 있지 않은 문자열이 필요합니다.")
        if message_id not in seen:
            seen.add(message_id)
            result.append(message_id)
    return result


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
    failed_retry: bool = False
    accumulated_waiting_time: float = 0.0

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

        if type(self.failed_retry) is not bool:
            raise TypeError("failed_retry는 bool이어야 합니다.")

        if isinstance(self.accumulated_waiting_time, bool) or not isinstance(
            self.accumulated_waiting_time, (int, float)
        ):
            raise TypeError("accumulated_waiting_time은 숫자여야 합니다.")
        if not math.isfinite(self.accumulated_waiting_time):
            raise ValueError("accumulated_waiting_time은 유한한 숫자여야 합니다.")
        if self.accumulated_waiting_time < 0:
            raise ValueError("accumulated_waiting_time은 0 이상이어야 합니다.")

        object.__setattr__(self, "key", self.key.upper())
        object.__setattr__(self, "enqueued_at", float(self.enqueued_at))
        object.__setattr__(
            self, "accumulated_waiting_time", float(self.accumulated_waiting_time)
        )

    def for_p2p_transfer(
        self, transfer_started_at: float, new_enqueued_at: float
    ) -> WorkerTask:
        """P2P 이전 전 대기시간을 보존한 새 Worker용 작업을 반환한다."""
        if isinstance(transfer_started_at, bool) or not isinstance(
            transfer_started_at, (int, float)
        ):
            raise TypeError("transfer_started_at은 숫자여야 합니다.")
        if not math.isfinite(transfer_started_at) or transfer_started_at < 0:
            raise ValueError("transfer_started_at은 0 이상의 유한한 숫자여야 합니다.")
        if transfer_started_at < self.enqueued_at:
            raise ValueError(
                "transfer_started_at은 현재 enqueued_at보다 빠를 수 없습니다."
            )

        if isinstance(new_enqueued_at, bool) or not isinstance(
            new_enqueued_at, (int, float)
        ):
            raise TypeError("new_enqueued_at은 숫자여야 합니다.")
        if not math.isfinite(new_enqueued_at) or new_enqueued_at < 0:
            raise ValueError("new_enqueued_at은 0 이상의 유한한 숫자여야 합니다.")
        if new_enqueued_at < transfer_started_at:
            raise ValueError(
                "new_enqueued_at은 transfer_started_at보다 빠를 수 없습니다."
            )

        waiting_before_transfer = float(transfer_started_at) - self.enqueued_at

        return replace(
            self,
            enqueued_at=float(new_enqueued_at),
            reserved_transfer_id=None,
            accumulated_waiting_time=(
                self.accumulated_waiting_time + waiting_before_transfer
            ),
        )


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
        self._completed_transfer_ids: set[str] = set()
        self._queue_version = 0
        self._lock = RLock()

    def get_queue_size(self) -> int:
        """예약된 작업을 포함한 현재 대기 작업 수를 반환한다."""
        with self._lock:
            return len(self._queue)

    def get_queue_state(self) -> tuple[int, int]:
        """같은 시점의 대기 작업 수와 Queue 버전을 함께 반환한다."""
        with self._lock:
            return len(self._queue), self._queue_version

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
            self._queue_version += 1
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
                    self._queue_version += 1
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
            if transfer_id in self._completed_transfer_ids:
                return []

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

            if reserved_tasks:
                self._queue_version += 1

        return reserved_tasks

    def confirm_transfer(self, transfer_id: str) -> list[WorkerTask]:
        """해당 전송 ID로 예약된 작업을 Queue에서 제거하여 반환한다."""
        _validate_transfer_id(transfer_id)

        removed_tasks: list[WorkerTask] = []

        # 원래 Queue 순서를 유지하면서 예약이 일치하지 않는 작업만 남긴다.
        with self._lock:
            if transfer_id in self._completed_transfer_ids:
                return []

            remaining_tasks: deque[WorkerTask] = deque()

            for task in self._queue:
                if task.reserved_transfer_id == transfer_id:
                    removed_tasks.append(task)
                else:
                    remaining_tasks.append(task)

            self._queue = remaining_tasks

            if removed_tasks:
                self._completed_transfer_ids.add(transfer_id)
                self._queue_version += 1

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

            if canceled_count:
                self._queue_version += 1

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


class WorkerStats:
    """Worker의 처리 결과와 성능 평가 통계를 관리한다."""

    def __init__(self) -> None:
        """모든 통계값을 0으로 초기화한다."""
        self.success_count = 0
        self.failure_count = 0
        self.processing_start_count = 0
        self.total_waiting_time = 0.0
        self.p2p_event_count = 0
        self.reassignment_count = 0
        self.total_execution_time = 0.0

        self._recorded_transfer_ids: set[str] = set()
        self._recorded_reassignments: set[tuple[str, int]] = set()
        self._lock = RLock()

    def record_processing_start(
        self, task: WorkerTask, started_at: float
    ) -> float:
        """처리 시작을 기록하고 작업의 대기시간을 반환한다."""
        if not isinstance(task, WorkerTask):
            raise TypeError("task는 WorkerTask 객체여야 합니다.")
        if isinstance(started_at, bool) or not isinstance(started_at, (int, float)):
            raise TypeError("started_at은 숫자여야 합니다.")
        if not math.isfinite(started_at):
            raise ValueError("started_at은 유한한 숫자여야 합니다.")
        if started_at < 0:
            raise ValueError("started_at은 0 이상이어야 합니다.")
        if started_at < task.enqueued_at:
            raise ValueError("started_at은 task.enqueued_at보다 빠를 수 없습니다.")

        waiting_time = (
            task.accumulated_waiting_time + float(started_at) - task.enqueued_at
        )

        # 합계와 횟수를 같은 잠금 안에서 변경해 평균 계산이 어긋나지 않게 한다.
        with self._lock:
            self.total_waiting_time += waiting_time
            self.processing_start_count += 1

        return waiting_time

    def record_success(self) -> None:
        """성공적으로 저장한 고유 KV 수를 1 증가시킨다."""
        with self._lock:
            self.success_count += 1

    def record_failure(self) -> None:
        """작업 처리 실패 횟수를 1 증가시킨다."""
        with self._lock:
            self.failure_count += 1

    def record_p2p_event(self, transfer_id: str) -> bool:
        """완료된 고유 P2P 전송을 한 번만 기록한다."""
        _validate_transfer_id(transfer_id)

        # 같은 전송의 ACK가 다시 처리되어도 이벤트 수를 중복 증가시키지 않는다.
        with self._lock:
            if transfer_id in self._recorded_transfer_ids:
                return False

            self._recorded_transfer_ids.add(transfer_id)
            self.p2p_event_count += 1
            return True

    def record_reassignment(self, task: WorkerTask) -> bool:
        """새로운 재할당 작업을 한 번만 기록한다."""
        if not isinstance(task, WorkerTask):
            raise TypeError("task는 WorkerTask 객체여야 합니다.")
        if not task.failed_retry:
            return False

        reassignment_id = (task.key, task.attempt)

        # Key와 시도 번호가 같은 재할당은 중복 집계하지 않는다.
        with self._lock:
            if reassignment_id in self._recorded_reassignments:
                return False

            self._recorded_reassignments.add(reassignment_id)
            self.reassignment_count += 1
            return True

    def set_total_execution_time(self, total_time: float) -> None:
        """Master가 전달한 가상 전체 수행시간을 저장한다."""
        if isinstance(total_time, bool) or not isinstance(total_time, (int, float)):
            raise TypeError("total_time은 숫자여야 합니다.")
        if not math.isfinite(total_time):
            raise ValueError("total_time은 유한한 숫자여야 합니다.")
        if total_time < 0:
            raise ValueError("total_time은 0 이상이어야 합니다.")

        with self._lock:
            self.total_execution_time = float(total_time)

    def get_average_waiting_time(self) -> float:
        """처리를 시작한 작업들의 평균 대기시간을 반환한다."""
        with self._lock:
            if self.processing_start_count == 0:
                return 0.0

            return self.total_waiting_time / self.processing_start_count

    def snapshot(self) -> dict[str, int | float]:
        """성능 평가에 필요한 현재 통계를 새 dict로 반환한다."""
        with self._lock:
            if self.processing_start_count == 0:
                average_waiting_time = 0.0
            else:
                average_waiting_time = (
                    self.total_waiting_time / self.processing_start_count
                )

            return {
                "throughput": self.success_count,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "average_waiting_time": average_waiting_time,
                "p2p_event_count": self.p2p_event_count,
                "reassignment_count": self.reassignment_count,
                "total_execution_time": self.total_execution_time,
            }


class Worker:
    """Master 메시지를 순서대로 받아 작업을 처리하는 Worker 한 개."""

    def __init__(
        self, worker_id: int, master_host: str, master_port: int,
        peer_host: str, peer_port: int, log_dir="logs", seed=None,
    ) -> None:
        if type(worker_id) is not int or worker_id not in range(1, 5):
            raise ValueError("worker_id는 1~4의 정수여야 합니다.")
        for host in (master_host, peer_host):
            if not isinstance(host, str) or not host.strip():
                raise ValueError("host는 비어 있지 않은 문자열이어야 합니다.")
        for port in (master_port, peer_port):
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("port는 1~65535의 정수여야 합니다.")

        self.worker_id = worker_id
        self.master_host = master_host
        self.master_port = master_port
        self.peer_host = peer_host
        self.peer_port = peer_port
        self.log_dir = log_dir
        self.ready_queue = WorkerReadyQueue()
        self.storage = WorkerStorage()
        self.stats = WorkerStats()
        self.sock: socket.socket | None = None
        self.connection: JsonLineConnection | None = None
        self.logger: NodeLogger | None = None
        self.peers: list[dict] = []
        self.clock = 0.0
        self.current_task: WorkerTask | None = None
        self.processing_time: int | None = None
        self.process_request_id: str | None = None
        self.pending_tasks: dict[str, dict] = {}
        self.message_number = 0
        self.running = False
        self.ready = False
        self.rng = random.Random(seed)
        self._message_lock = RLock()
        self._responses: dict[str, dict | None] = {}
        self._state_lock = RLock()
        self.timeout = 60
        self.p2p = P2PNode(
            worker_id, peer_host, peer_port,
            self.ready_queue.get_queue_state, self._receive_transfer,
        )
        self._closing = Event()
        self._pending_times: dict[str, dict] = {}
        self._received_transfers: dict[str, dict] = {}
        self._outgoing_transfers: dict[str, dict] = {}
        self._incoming_slots = 0
        self._active_p2p_check: str | None = None
        self._p2p_threads: list[Thread] = []
        self._p2p_failed = False
        self._p2p_error: Exception | None = None

    @property
    def queue_version(self) -> int:
        """Queue가 관리하는 최신 버전을 조회한다."""
        return self.ready_queue.get_queue_state()[1]

    def log(self, event: str, status: str, message: str, clock=None) -> None:
        """Master가 확정한 시각으로 기존 로거에 기록한다."""
        if self.logger is not None:
            self.logger.log(self.clock if clock is None else clock, event, status, message)

    def create_message(self, kind: str, **data) -> dict:
        """새 논리 메시지의 ID와 공통 필드를 만든다."""
        if kind in {"P2P_TIME", "P2P_COST", "P2P_TRANSFER", "P2P_FAILURE"}:
            data["communication_ids"] = _unique_communication_ids(data["communication_ids"])
        with self._message_lock:
            self.message_number += 1
            return {
                **data,
                "type": kind,
                "sender": f"WORKER{self.worker_id}",
                "receiver": "MASTER",
                "message_id": f"worker-{self.worker_id}-{self.message_number}",
                "clock": self.clock,
            }

    def send_message(self, message: dict) -> None:
        """이미 만든 메시지를 전송한다. 재전송 시에도 기존 ID를 유지한다."""
        if self.connection is None:
            raise ConnectionClosed("Master에 연결되어 있지 않습니다.")
        self.connection.send(message)

    @staticmethod
    def _read_time(message: dict, name: str) -> float:
        """메시지의 가상 시각 또는 시간 값을 검증한다."""
        value = message[name]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name}은 0 이상의 유한한 숫자여야 합니다.")
        return float(value)

    @staticmethod
    def _task_identity(message: dict) -> tuple[str, int]:
        """수신한 작업의 Key와 시도 번호를 확인한다."""
        key, attempt = message["key"], message["attempt"]
        if not isinstance(key, str) or len(key) != 4:
            raise ValueError("key는 4자리 문자열이어야 합니다.")
        if any(character not in "0123456789abcdefABCDEF" for character in key):
            raise ValueError("key는 16진수여야 합니다.")
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attempt는 1 이상의 정수여야 합니다.")
        return key.upper(), attempt

    def _log_queue_change(self, before: int, after: int, clock: float) -> None:
        """크기 8 이상이 관련된 각 입출력에 WARN을 기록한다."""
        if max(before, after) > MAX_QUEUE_SIZE * 0.7:
            self.log("QUEUE_STATUS", "WARN", f"대기 작업 수 {before} -> {after}", clock)

    def _handle_peers(self, message: dict) -> dict:
        """Worker 주소 목록을 저장하고 READY 메시지를 만든다."""
        if self.ready:
            raise ValueError("이미 READY를 보낸 Worker입니다.")
        peers = message["peers"]
        if not isinstance(peers, list):
            raise ValueError("peers는 주소 목록이어야 합니다.")
        worker_ids = set()
        for peer in peers:
            if not isinstance(peer, dict):
                raise ValueError("Worker 주소는 dict여야 합니다.")
            worker_id = peer["worker_id"]
            if type(worker_id) is not int or worker_id not in range(1, 5):
                raise ValueError("잘못된 peer worker_id입니다.")
            if worker_id in worker_ids:
                raise ValueError("중복된 peer worker_id입니다.")
            worker_ids.add(worker_id)
            if not isinstance(peer["host"], str) or not peer["host"].strip():
                raise ValueError("peer host가 필요합니다.")
            if type(peer["port"]) is not int or not 1 <= peer["port"] <= 65535:
                raise ValueError("peer port 범위 오류입니다.")
        if worker_ids != {1, 2, 3, 4}:
            raise ValueError("Worker 4개의 주소가 필요합니다.")
        self.peers = [peer.copy() for peer in peers]
        self.p2p.set_peers(self.peers)
        self.p2p.start()
        self.log("INIT", "SUCCESS", f"P2P 서버 시작 {self.peer_host}:{self.peer_port}")
        return self.create_message("READY", request_id=message["message_id"])

    def _handle_task(self, message: dict) -> dict:
        """확인 대기 작업까지 포함해 수락 여부를 결정한다."""
        key, attempt = self._task_identity(message)
        value = message["value"]
        if type(value) is not int or not 1 <= value <= 100:
            raise ValueError("value는 1~100의 정수여야 합니다.")
        if type(message["is_retry"]) is not bool or type(message["failed_retry"]) is not bool:
            raise ValueError("is_retry와 failed_retry는 bool이어야 합니다.")

        # 확인 대기 작업도 자리를 차지한다. 아직 처리 가능한 Queue에는 넣지 않는다.
        with self.ready_queue._lock:
            accepted = self.ready_queue.has_capacity(
                len(self.pending_tasks) + self._incoming_slots + 1
            )
            size, version = self.ready_queue.get_queue_state()
            response = self.create_message(
                "TASK_ACK", request_id=message["message_id"], key=key,
                attempt=attempt, accepted=accepted, queue_size=size, queue_version=version,
            )
            if accepted:
                self.pending_tasks[response["message_id"]] = {
                    "key": key, "value": value, "attempt": attempt,
                    "failed_retry": message["failed_retry"],
                }

        self.log("TASK", "INFO", f"수신 key={key} attempt={attempt}")
        self.log("TASK_ACK", "SUCCESS" if accepted else "FAIL", f"key={key} accepted={accepted}")
        return response

    def _handle_task_confirmed(self, message: dict) -> dict:
        """수락 ACK와 일치하는 작업을 확정 시각으로 Queue에 넣는다."""
        request_id = message["request_id"]
        pending = self.pending_tasks.get(request_id)
        if pending is None or self._task_identity(message) != (pending["key"], pending["attempt"]):
            raise ValueError("TASK_CONFIRMED와 수락 대기 작업이 일치하지 않습니다.")
        enqueued_at = self._read_time(message, "enqueued_at")
        if enqueued_at > self.clock:
            raise ValueError("큐 진입 시각이 Master 확정 시각보다 늦습니다.")
        task = WorkerTask(**pending, enqueued_at=enqueued_at)

        # 변경 전후 크기도 같은 잠금으로 읽고, 송신과 로그는 잠금 밖에서 처리한다.
        with self.ready_queue._lock:
            before, _ = self.ready_queue.get_queue_state()
            if not self.ready_queue.enqueue(task):
                raise ValueError("수락한 작업을 넣을 Queue 공간이 없습니다.")
            del self.pending_tasks[request_id]
            size, version = self.ready_queue.get_queue_state()

        self._log_queue_change(before, size, enqueued_at)
        self.log("TASK_ACK", "INFO", f"Queue 진입 key={task.key}", enqueued_at)
        if task.failed_retry and self.stats.record_reassignment(task):
            self.log("REASSIGN", "INFO", f"실패 재할당 접수 key={task.key} attempt={task.attempt}", enqueued_at)
        return self.create_message(
            "QUEUE_STATUS", request_id=message["message_id"],
            queue_size=size, queue_version=version,
        )

    def start_next_task(self) -> None:
        """처리 중인 작업이 없으면 PROCESS_START를 보내고 수신 반복으로 돌아간다."""
        if self._p2p_failed or not self.running or not self.ready or self.current_task is not None:
            return
        with self.ready_queue._lock:
            before, _ = self.ready_queue.get_queue_state()
            task = self.ready_queue.dequeue()
            size, version = self.ready_queue.get_queue_state()
        if task is None:
            return

        self.current_task = task
        self.processing_time = self.rng.randint(1, 3)
        message = self.create_message(
            "PROCESS_START", key=task.key, attempt=task.attempt,
            processing_time=self.processing_time, queue_size=size, queue_version=version,
        )
        self.process_request_id = message["message_id"]
        self._log_queue_change(before, size, self.clock)
        self.log("PROC", "INFO", f"처리 요청 key={task.key} processing_time={self.processing_time}")
        self.send_message(message)

    def _handle_process_ack(self, message: dict) -> dict:
        """확정 처리 시각을 확인하고 성공 또는 실패 결과를 만든다."""
        task = self.current_task
        if (task is None or message["request_id"] != self.process_request_id
                or self._task_identity(message) != (task.key, task.attempt)):
            raise ValueError("PROCESS_ACK와 현재 처리 작업이 일치하지 않습니다.")
        started_at = self._read_time(message, "started_at")
        finished_at = self._read_time(message, "finished_at")
        master_waiting_time = self._read_time(message, "waiting_time")
        if (finished_at > self.clock or not math.isclose(
                finished_at - started_at, self.processing_time, abs_tol=1e-9)):
            raise ValueError("PROCESS_ACK 처리 시각과 처리시간이 일치하지 않습니다.")
        waiting_time = self.stats.record_processing_start(task, started_at)
        if not math.isclose(waiting_time, master_waiting_time, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("Master와 Worker의 대기시간이 일치하지 않습니다.")
        self.log("PROC", "INFO", f"처리 시작 key={task.key} waiting_time={waiting_time}", started_at)

        status = "SUCCESS" if self.rng.random() < 0.8 else "FAIL"
        if status == "SUCCESS":
            if self.storage.store(task):
                self.stats.record_success()
        else:
            self.stats.record_failure()
        self.log("RESULT", status, f"key={task.key} value={task.value} attempt={task.attempt}", finished_at)
        size, version = self.ready_queue.get_queue_state()
        return self.create_message(
            "RESULT", request_id=message["message_id"], key=task.key,
            value=task.value, attempt=task.attempt, status=status,
            processing_time=self.processing_time, waiting_time=waiting_time,
            queue_size=size, queue_version=version,
        )

    def _report_p2p_queue(self, before: int, state: tuple[int, int], clock: float) -> None:
        """P2P로 바뀐 Queue의 버전과 경고를 보고한다. Queue 잠금 밖에서 호출한다."""
        size, version = state
        self._log_queue_change(before, size, clock)
        self.send_message(self.create_message(
            "QUEUE_STATUS", queue_size=size, queue_version=version,
        ))

    def _request_p2p_time(
        self, transfer_id: str, source: int, target: int, phase: str,
        communication_ids: list[str],
    ) -> float:
        """P2P 스레드에서 확정 시각을 기다린다. Master 수신 스레드는 기다리지 않는다."""
        with self._state_lock:
            if self._closing.is_set():
                raise ConnectionClosed("Worker가 종료 중입니다.")
            request = self.create_message(
                "P2P_TIME", transfer_id=transfer_id, source=source, target=target,
                phase=phase, communication_ids=communication_ids,
            )
            pending = {
                "transfer_id": transfer_id, "phase": phase,
                "event": Event(), "response": None,
            }
            self._pending_times[request["message_id"]] = pending

        # 응답이 바로 와도 놓치지 않도록 먼저 등록하고, 잠금을 풀고 송신·대기한다.
        try:
            self.send_message(request)
            if not pending["event"].wait(self.timeout):
                raise TimeoutError(f"TIME_ACK 시간 초과: {transfer_id} {phase}")
            with self._state_lock:
                if self._closing.is_set() or pending["response"] is None:
                    raise ConnectionClosed("TIME_ACK 대기 중 Worker가 종료되었습니다.")
                return pending["response"]["event_at"]
        finally:
            with self._state_lock:
                self._pending_times.pop(request["message_id"], None)

    def _handle_time_ack(self, message: dict) -> None:
        """요청 ID, 이전 ID, 단계가 모두 맞는 대기 스레드에만 시각을 전달한다."""
        pending = self._pending_times.get(message["request_id"])
        if pending is None:
            self.log("P2P_TRANSFER", "WARN", "대기가 끝난 TIME_ACK 수신, 예약 상태 유지")
            return
        if (message["transfer_id"] != pending["transfer_id"]
                or message["phase"] != pending["phase"]):
            raise ValueError("TIME_ACK의 전송 ID 또는 단계가 요청과 다릅니다.")
        event_at = self._read_time(message, "event_at")
        if event_at > self.clock:
            raise ValueError("P2P 이벤트 시각이 Master 시각보다 늦습니다.")
        if pending["response"] is not None and pending["response"]["event_at"] != event_at:
            raise ValueError("같은 P2P 시각 요청에 다른 시각이 전달되었습니다.")
        pending["response"] = message.copy()
        pending["event"].set()

    def _receive_transfer(
        self, transfer_id: str, source_id: int, tasks: list[dict], transfer_message_id: str,
    ) -> tuple[bool, str]:
        """P2PNode 콜백: 공간을 확보하고 수신 시각을 받아 예약된 작업을 넣는다."""
        _validate_transfer_id(transfer_id)
        if not isinstance(transfer_message_id, str) or not transfer_message_id.strip():
            raise ValueError("P2P 직접 전송의 message_id가 필요합니다.")
        if type(source_id) is not int or source_id not in range(1, 5) or source_id == self.worker_id:
            raise ValueError("P2P 송신 Worker ID가 올바르지 않습니다.")
        incoming = [WorkerTask(**item) for item in clean_tasks(tasks)]
        started_at = incoming[0].enqueued_at
        if any(task.enqueued_at != started_at for task in incoming):
            raise ValueError("한 번에 이전할 작업의 SEND 시각은 같아야 합니다.")

        with self._state_lock:
            if self._closing.is_set():
                raise ConnectionClosed("Worker가 종료 중입니다.")
            previous = self._received_transfers.get(transfer_id)
            if previous is not None:
                if previous["source"] != source_id or previous["tasks"] != incoming:
                    return False, "같은 transfer_id의 송신자 또는 작업 내용이 다릅니다."
                if previous["status"] in {"ACCEPTED", "CONFIRMED"}:
                    return True, "이미 수신한 이전입니다."
                if previous["status"] == "REJECTED":
                    return False, "Queue 공간 부족으로 거절한 이전입니다."
                raise TimeoutError("기존 이전의 수신 시각이 아직 확정되지 않았습니다.")
            record = {"source": source_id, "tasks": incoming, "status": "PENDING"}
            self._received_transfers[transfer_id] = record
            with self.ready_queue._lock:
                needed = len(self.pending_tasks) + self._incoming_slots + len(incoming)
                if not self.ready_queue.has_capacity(needed):
                    record["status"] = "REJECTED"
                    return False, "전체 작업을 받을 Queue 공간이 부족합니다."
                # TIME_ACK 대기 중 Master 작업이 이 공간을 차지하지 못하게 한다.
                self._incoming_slots += len(incoming)

        try:
            # 잠금을 풀고 기다린다. 직접 전송 비용은 RECV 시각 확정 전에 반영한다.
            arrived_at = self._request_p2p_time(
                transfer_id, source_id, self.worker_id, "RECV", [transfer_message_id],
            )
            if arrived_at < started_at:
                raise ValueError("RECV 시각이 SEND 시각보다 빠릅니다.")
            with self._state_lock:
                if self._closing.is_set():
                    raise ConnectionClosed("P2P 수신 확정 중 Worker가 종료되었습니다.")
                changes = []
                with self.ready_queue._lock:
                    for task in incoming:
                        before, _ = self.ready_queue.get_queue_state()
                        received_task = replace(
                            task, enqueued_at=arrived_at, reserved_transfer_id=transfer_id,
                        )
                        if not self.ready_queue.enqueue(received_task):
                            raise RuntimeError("P2P 수신을 위해 확보한 Queue 공간이 부족합니다.")
                        changes.append((before, self.ready_queue.get_queue_state()))
                    self._incoming_slots -= len(incoming)
                record.update(status="ACCEPTED", arrived_at=arrived_at, started_at=started_at)
                for before, state in changes:
                    self._report_p2p_queue(before, state, arrived_at)
                self.log("P2P_ACK", "INFO", f"id={transfer_id} 수신, Master 이전 확정 대기", arrived_at)
            return True, f"작업 {len(incoming)}개 수신 완료"
        except Exception:
            with self._state_lock:
                # 불확실한 수신은 거절로 응답하지 않는다. 확보한 공간과 작업을 보존한다.
                if record["status"] == "PENDING":
                    record["status"] = "UNKNOWN"
                self.log("P2P_ACK", "WARN", f"id={transfer_id} 수신 확인 미완료, 상태 보존")
            raise

    def _handle_transfer_confirmed(self, message: dict) -> dict:
        """Master가 소유권을 확정한 이전만 예약 해제하고 한 번 집계한다."""
        transfer_id = message["transfer_id"]
        _validate_transfer_id(transfer_id)
        record = self._received_transfers.get(transfer_id)
        if record is None or record["status"] not in {"ACCEPTED", "CONFIRMED"}:
            raise ValueError("수신 완료되지 않은 이전의 TRANSFER_CONFIRMED입니다.")
        # 현재 Master는 source 필드 대신 송신 보고의 message_id를 request_id로 전달한다.
        request_id = message["request_id"]
        prefix = f"worker-{record['source']}-"
        if (not isinstance(request_id, str) or not request_id.startswith(prefix)
                or not request_id[len(prefix):].isdigit()):
            raise ValueError("이전 확정의 송신 Worker가 수신 기록과 다릅니다.")
        identities = [self._task_identity(item) for item in message["tasks"]]
        expected = [(task.key, task.attempt) for task in record["tasks"]]
        if sorted(identities) != sorted(expected):
            raise ValueError("이전 확정 작업 목록이 수신 기록과 다릅니다.")
        if (self._read_time(message, "transfer_started_at") != record["started_at"]
                or self._read_time(message, "new_enqueued_at") != record["arrived_at"]):
            raise ValueError("이전 확정 시각이 TIME_ACK와 다릅니다.")
        if record["status"] == "CONFIRMED":
            if request_id != record["request_id"]:
                raise ValueError("같은 이전을 확정한 원래 요청 ID가 다릅니다.")
            return record["response"]

        with self.ready_queue._lock:
            before, _ = self.ready_queue.get_queue_state()
            reserved = [
                (task.key, task.attempt) for task in self.ready_queue.snapshot()
                if task.reserved_transfer_id == transfer_id
            ]
            if sorted(reserved) != sorted(expected):
                raise ValueError("이전 확정 작업의 Queue 예약 목록이 다릅니다.")
            self.ready_queue.cancel_transfer(transfer_id)
            size, version = self.ready_queue.get_queue_state()
        self._log_queue_change(before, size, self.clock)
        self.stats.record_p2p_event(transfer_id)
        self.log("P2P_TRANSFER", "SUCCESS", f"id={transfer_id} 수신 작업 처리 가능")
        response = self.create_message(
            "QUEUE_STATUS", request_id=message["message_id"],
            queue_size=size, queue_version=version,
        )
        record.update(status="CONFIRMED", request_id=request_id, response=response)
        return response

    def _handle_p2p_check(self, message: dict) -> None:
        """조회·이전은 별도 스레드에 맡겨 Master 수신 반복문을 유지한다."""
        if self._p2p_failed:
            return
        if self._active_p2p_check is not None:
            raise ValueError("기존 P2P 점검이 아직 끝나지 않았습니다.")
        self._active_p2p_check = message["message_id"]
        self._p2p_threads = [thread for thread in self._p2p_threads if thread.is_alive()]
        thread = Thread(
            target=self._run_p2p_check, args=(message.copy(),),
            name=f"Worker{self.worker_id}-P2P-check",
        )
        self._p2p_threads.append(thread)
        thread.start()

    def _finish_p2p_check(self, request_id: str, response: dict) -> None:
        """완료 응답을 캐시에 보관해 같은 점검 요청에는 같은 메시지를 재전송한다."""
        with self._state_lock:
            self._responses[request_id] = response
            self._active_p2p_check = None
            if response["type"] == "P2P_FAILURE":
                self._p2p_failed = True
            if not self._closing.is_set():
                self.send_message(response)
                if not self._p2p_failed:
                    self.start_next_task()

    def _handle_p2p_exception(
        self, request_id: str, transfer_id: str, target_id: int | None,
        send_confirmed: bool, communication_ids: list[str], error: Exception,
    ) -> None:
        """보고 가능한 이전은 Master에 알리고, 그 외 예외는 메인 run()으로 전달한다."""
        with self._state_lock:
            self._active_p2p_check = None
            if self._closing.is_set():
                return
            self._p2p_failed = True
            reason = f"P2P 점검 예외: {type(error).__name__}: {error}"
            record = self._outgoing_transfers.get(transfer_id)
            if record is not None:
                record["error"] = reason

            # 최종 보고가 이미 만들어졌다면 Master가 이전 정보를 정리했을 수 있다.
            if send_confirmed and self._responses.get(request_id) is None:
                try:
                    response = self.create_message(
                        "P2P_FAILURE", request_id=request_id, transfer_id=transfer_id,
                        source=self.worker_id, target=target_id, reason=reason,
                        communication_ids=communication_ids,
                    )
                    self.log("P2P_TRANSFER", "FAIL", f"id={transfer_id} {reason}, 예약 유지")
                    self._finish_p2p_check(request_id, response)
                    return
                except Exception:
                    # 실패 보고도 보낼 수 없으면 원래 P2P 예외를 메인 스레드에 넘긴다.
                    pass
            if self._p2p_error is None:
                self._p2p_error = error
            sock = self.sock

        # recv()와 Master의 연결 대기를 깨운다. close와 스레드 정리는 run()이 맡는다.
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _run_p2p_check(self, message: dict) -> None:
        """이웃 조회, SEND 시각 확정, 직접 전송과 수신 상태 확인을 순서대로 수행한다."""
        request_id = message["message_id"]
        transfer_id = f"transfer-{self.worker_id}-{request_id}"
        target_id = None
        communication_ids = []
        send_confirmed = False
        try:
            with self._state_lock:
                if self._closing.is_set():
                    return
                size, version = self.ready_queue.get_queue_state()
                if size * 2 <= 15:
                    response = self.create_message(
                        "P2P_COST", request_id=request_id, communication_ids=[],
                    )
                    self._finish_p2p_check(request_id, response)
                    return
                clock = self.clock
            target = self.p2p.find_transfer_target(size, clock)
            communication_ids = _unique_communication_ids(target["communication_ids"])
            target_id = target["target_worker_id"]
            with self._state_lock:
                if self._closing.is_set():
                    return
                with self.ready_queue._lock:
                    before, current_version = self.ready_queue.get_queue_state()
                    tasks = []
                    # 조회 중 일반 처리가 진행될 수 있으므로 예약 직전에 다시 검사한다.
                    if before * 2 > 15 and target_id is not None:
                        count = target["transfer_count"]
                        if current_version != version:
                            count = min(count, max(0, (before - target["target_queue_size"]) // 2))
                        if count > 0:
                            tasks = self.ready_queue.reserve_for_transfer(transfer_id, count)
                    state = self.ready_queue.get_queue_state()
                if not tasks:
                    response = self.create_message(
                        "P2P_COST", request_id=request_id, communication_ids=communication_ids,
                    )
                    self._finish_p2p_check(request_id, response)
                    return
                record = {
                    "request_id": request_id, "target": target_id, "tasks": tasks,
                    "status": "RESERVED", "communication_ids": communication_ids,
                }
                self._outgoing_transfers[transfer_id] = record
                self._report_p2p_queue(before, state, self.clock)

            started_at = self._request_p2p_time(
                transfer_id, self.worker_id, target_id, "SEND", communication_ids,
            )
            send_confirmed = True
            payload = []
            for task in tasks:
                moved = task.for_p2p_transfer(started_at, started_at)
                payload.append({
                    "key": moved.key, "value": moved.value, "attempt": moved.attempt,
                    "enqueued_at": moved.enqueued_at, "failed_retry": moved.failed_retry,
                    "accumulated_waiting_time": moved.accumulated_waiting_time,
                })
            if self._closing.is_set():
                return
            result = self.p2p.send_transfer(target_id, transfer_id, payload, started_at)
            communication_ids = _unique_communication_ids(communication_ids + result["communication_ids"])
            with self._state_lock:
                record["communication_ids"] = communication_ids
            for _ in range(3):
                if result["status"] != "UNKNOWN" or self._closing.is_set():
                    break
                with self._state_lock:
                    clock = self.clock
                result = self.p2p.check_transfer(target_id, transfer_id, clock)
                communication_ids = _unique_communication_ids(communication_ids + result["communication_ids"])
                with self._state_lock:
                    record["communication_ids"] = communication_ids

            with self._state_lock:
                record.update(status=result["status"], communication_ids=communication_ids)
                if self._closing.is_set():
                    return
                if result["status"] == "UNKNOWN":
                    reason = f"상태 조회 3회 모두 UNKNOWN: {result['reason']}"
                    record.update(status="UNRECOVERABLE_UNKNOWN", reason=reason)
                    response = self.create_message(
                        "P2P_FAILURE", request_id=request_id, transfer_id=transfer_id,
                        source=self.worker_id, target=target_id, reason=reason,
                        communication_ids=communication_ids,
                    )
                    self.log("P2P_TRANSFER", "FAIL", f"id={transfer_id} {reason}, 예약 유지")
                    self._finish_p2p_check(request_id, response)
                    return
                with self.ready_queue._lock:
                    before, _ = self.ready_queue.get_queue_state()
                    if result["status"] == "ACCEPTED":
                        self.ready_queue.confirm_transfer(transfer_id)
                    elif result["status"] == "REJECTED":
                        self.ready_queue.cancel_transfer(transfer_id)
                    else:
                        raise ValueError("알 수 없는 P2P 이전 결과입니다.")
                    state = self.ready_queue.get_queue_state()
                self._report_p2p_queue(before, state, self.clock)
                if result["status"] == "ACCEPTED":
                    self.stats.record_p2p_event(transfer_id)
                    response = self.create_message(
                        "P2P_TRANSFER", request_id=request_id, transfer_id=transfer_id,
                        source=self.worker_id, target=target_id,
                        tasks=[{"key": task.key, "attempt": task.attempt} for task in tasks],
                        communication_ids=communication_ids,
                    )
                else:
                    response = self.create_message(
                        "P2P_COST", request_id=request_id, transfer_id=transfer_id,
                        communication_ids=communication_ids,
                    )
                self.log("P2P_ACK", "INFO", f"id={transfer_id} {result['status']}: {result['reason']}")
                self._finish_p2p_check(request_id, response)
        except Exception as error:
            self._handle_p2p_exception(
                request_id, transfer_id, target_id, send_confirmed, communication_ids, error,
            )

    def _stop_p2p(self) -> None:
        """시각 대기를 깨운 후 P2P 서버와 점검 스레드를 정리한다."""
        self._closing.set()
        with self._state_lock:
            self._active_p2p_check = None
            for pending in self._pending_times.values():
                pending["event"].set()
            threads = list(self._p2p_threads)
        self.p2p.stop()
        # P2PNode의 소켓 호출은 timeout이 있으며, 종료 후에는 다음 전송을 시작하지 않는다.
        for thread in threads:
            thread.join()

    def _handle_stop(self, message: dict) -> dict:
        """Master가 전달한 종료 기준 통계를 STOP_ACK로 반환한다."""
        total_time = self._read_time(message, "total_execution_time")
        completed_at = self._read_time(message, "work_completed_at")
        if completed_at > self.clock:
            raise ValueError("작업 완료 시각이 종료 요청 시각보다 늦습니다.")
        self.stats.set_total_execution_time(total_time)
        stats = self.stats.snapshot()
        self.log("STOP", "INFO", f"종료 요청 work_completed_at={completed_at}")
        self.log("STAT", "INFO", f"stats_at={self.clock} {stats}")
        return self.create_message(
            "STOP_ACK", request_id=message["message_id"], stats=stats, stats_at=self.clock,
        )

    def handle_message(self, message: dict) -> None:
        """Master 메시지 처리와 P2P 스레드의 상태 변경이 겹치지 않게 한다."""
        with self._state_lock:
            self._handle_master_message(message)

    def _handle_master_message(self, message: dict) -> None:
        """Master 수신은 한 스레드만 담당하며 여기서는 TIME_ACK를 기다리지 않는다."""
        if not isinstance(message, dict):
            raise InvalidMessage("Master 메시지는 dict여야 합니다.")
        if message.get("sender") != "MASTER" or message.get("receiver") != f"WORKER{self.worker_id}":
            raise InvalidMessage("Master 메시지의 송수신 노드가 일치하지 않습니다.")
        message_id, kind = message["message_id"], message["type"]
        if not isinstance(message_id, str) or not message_id.strip():
            raise InvalidMessage("message_id가 필요합니다.")
        if not isinstance(kind, str) or not kind.strip():
            raise InvalidMessage("메시지 type이 필요합니다.")
        clock = self._read_time(message, "clock")

        # 동일 메시지는 상태와 난수를 다시 처리하지 않고 기존 응답만 재전송한다.
        if message_id in self._responses:
            response = self._responses[message_id]
            if response is not None:
                self.send_message(response)
            return
        self.clock = clock
        if not self.ready and kind != "PEERS":
            raise InvalidMessage("등록 후 첫 Master 메시지는 PEERS여야 합니다.")

        if kind == "PEERS":
            response = self._handle_peers(message)
        elif kind == "TASK":
            response = self._handle_task(message)
        elif kind == "TASK_CONFIRMED":
            response = self._handle_task_confirmed(message)
        elif kind == "PROCESS_ACK":
            response = self._handle_process_ack(message)
        elif kind == "P2P_CHECK":
            response = self._handle_p2p_check(message)
        elif kind == "TIME_ACK":
            response = self._handle_time_ack(message)
        elif kind == "TRANSFER_CONFIRMED":
            response = self._handle_transfer_confirmed(message)
        elif kind == "STOP":
            response = self._handle_stop(message)
        else:
            self.log("INIT", "WARN", f"아직 지원하지 않는 메시지: {kind}")
            response = None

        if response is not None:
            self.send_message(response)
        self._responses[message_id] = response
        if kind == "PEERS":
            self.ready = True
            self.log("INIT", "SUCCESS", "PEERS 저장 및 READY 전송 완료")
        elif kind == "PROCESS_ACK":
            self.current_task = None
            self.process_request_id = None
            self.processing_time = None
        elif kind == "STOP":
            self.running = False
            self.log("STOP_ACK", "SUCCESS", "최종 통계 응답 전송 완료")

        # 점검 스레드가 예약 대상을 고를 수 있도록 이 요청에서는 다음 작업을 꺼내지 않는다.
        if kind != "P2P_CHECK" and not self._p2p_failed:
            self.start_next_task()

    def run(self, timeout=60) -> None:
        """Master에 등록하고 STOP까지 메시지를 수신한다."""
        if self.running:
            raise RuntimeError("이미 실행 중인 Worker입니다.")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout은 유한한 양수여야 합니다.")
        self.timeout = timeout
        self.p2p.timeout = min(5, timeout)
        try:
            self.logger = NodeLogger(f"Worker{self.worker_id}", self.log_dir)
            self.log("INIT", "INFO", "Worker 초기화")
            self.sock = socket.create_connection((self.master_host, self.master_port), timeout)
            self.connection = JsonLineConnection(self.sock)
            self.running = True
            self.log("INIT", "SUCCESS", f"Master {self.master_host}:{self.master_port} 연결")
            hello = self.create_message(
                "HELLO", worker_id=self.worker_id,
                peer_host=self.peer_host, peer_port=self.peer_port,
            )
            self.send_message(hello)
            self.log("HELLO", "INFO", "등록 요청 전송")
            while self.running:
                message = self.connection.recv()
                with self._state_lock:
                    if self._p2p_error is not None:
                        raise self._p2p_error
                    self.handle_message(message)
        except Exception as error:
            with self._state_lock:
                p2p_error = self._p2p_error
            if p2p_error is not None:
                self.log("STOP", "FAIL", f"P2P 점검으로 Worker 실행 중단: {p2p_error}")
                raise RuntimeError(f"P2P 점검 실패: {p2p_error}") from p2p_error
            self.log("STOP", "FAIL", f"Worker 실행 중단: {error}")
            raise
        finally:
            self._closing.set()
            self.running = False
            if self.sock is not None:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.sock.close()
            self._stop_p2p()
            if self.logger is not None:
                try:
                    self.log("STOP", "INFO", "연결 종료")
                finally:
                    self.logger.close()
