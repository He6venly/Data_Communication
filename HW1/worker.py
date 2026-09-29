"""Worker의 자료구조, Master 연결, 작업 처리와 P2P 이전을 제공한다."""

from __future__ import annotations

import math
import json
import random
import socket
from collections import deque
from dataclasses import dataclass, replace
from threading import Event, RLock, Thread

from logger import NodeLogger
from p2p import P2PNode
from protocol import ConnectionClosed, InvalidMessage, JsonLineConnection


MAX_QUEUE_SIZE = 10


@dataclass(frozen=True)
class WorkerTask:
    """수신 단계에서 검사한 작업 정보. 예약 변경은 큐에서 처리."""

    key: str
    value: int
    attempt: int
    enqueued_at: float
    reserved_transfer_id: str | None = None
    failed_retry: bool = False
    accumulated_waiting_time: float = 0.0

    def for_p2p_transfer(
        self, transfer_started_at: float, new_enqueued_at: float
    ) -> WorkerTask:
        """P2P 이전 전 대기시간을 보존한 새 Worker용 작업을 반환한다."""
        waiting_before_transfer = transfer_started_at - self.enqueued_at
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
        """프로그램 내부에서 사용하는 대기 큐. 기본 용량은 10개."""

        self._queue: deque[WorkerTask] = deque()
        self._max_size = max_size
        self._completed_transfer_ids: set[str] = set()
        self._queue_version = 0
        self._lock = RLock()

    def get_queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    def get_queue_state(self) -> tuple[int, int]:
        """같은 시점의 대기 작업 수와 Queue 버전을 함께 반환한다."""
        with self._lock:
            return len(self._queue), self._queue_version

    def has_capacity(self, count: int = 1) -> bool:
        """count개의 작업을 추가할 공간이 있는지 확인한다."""

        with self._lock:
            return len(self._queue) + count <= self._max_size

    def enqueue(self, task: WorkerTask) -> bool:
        """공간이 있으면 작업을 Queue 뒤에 넣고 True를 반환한다."""

        # 크기 확인과 추가를 같은 잠금 안에서 처리해야 동시에 초과 삽입되지 않는다.
        with self._lock:
            if len(self._queue) >= self._max_size:
                return False

            self._queue.append(task)
            self._queue_version += 1
            return True

    def dequeue(self) -> WorkerTask | None:
        """예약되지 않은 재시도 작업을 먼저, 같은 종류는 FIFO로 반환한다.

        예약된 작업은 Queue 크기에는 포함되지만 일반 처리 대상으로는
        꺼내지 않는다. 처리할 수 있는 작업이 없으면 None을 반환한다.
        """
        with self._lock:
            for retry_only in (True, False):
                for index, task in enumerate(self._queue):
                    if task.reserved_transfer_id is None and (task.failed_retry or not retry_only):
                        del self._queue[index]
                        self._queue_version += 1
                        return task

            return None

    def reserve_for_transfer(
        self, transfer_id: str, count: int
    ) -> list[WorkerTask]:
        """뒤쪽 작업부터 예약. 같은 이전 ID는 기존 예약을 반환."""

        # 탐색과 예약 표시를 한 잠금 안에서 수행해 중복 예약을 막는다.
        with self._lock:
            if transfer_id in self._completed_transfer_ids:
                return []

            # 최초 호출과 같은 순서를 유지하기 위해 뒤쪽부터 기존 예약을 찾는다.
            reserved_tasks = [
                task for task in reversed(self._queue)
                if task.reserved_transfer_id == transfer_id
            ]

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

        removed_tasks: list[WorkerTask] = []

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


class Worker:
    """Master 메시지를 순서대로 받아 작업을 처리하는 Worker 한 개."""

    def __init__(
        self, worker_id: int, master_host: str, master_port: int,
        peer_host: str, peer_port: int, log_dir="logs", seed=None,
    ) -> None:

        self.worker_id = worker_id
        self.master_host = master_host
        self.master_port = master_port
        self.peer_host = peer_host
        self.peer_port = peer_port
        self.log_dir = log_dir
        self.ready_queue = WorkerReadyQueue()
        # 결과와 통계는 _state_lock 안에서 함께 변경한다.
        self.storage: dict[str, int] = {}
        self.failure_count = 0
        self.processing_count = 0
        self.total_waiting_time = 0.0
        self.total_execution_time = 0.0
        self.p2p_events: set[str] = set()
        self.reassignments: set[tuple[str, int]] = set()
        self.sock: socket.socket | None = None
        self.connection: JsonLineConnection | None = None
        self.logger: NodeLogger | None = None
        self.clock = 0.0
        self.current_task: WorkerTask | None = None
        self.processing_time: int | None = None
        self.process_request_id: str | None = None
        self.pending_tasks: dict[str, dict] = {}
        self.message_number = 0
        self.running = False
        self.ready = False
        self.stopping = False
        self.rng = random.Random(seed)
        self._message_lock = RLock()
        self._seen_messages: set[str] = set()
        self._state_lock = RLock()
        self.timeout = 60
        self.p2p = P2PNode(
            worker_id, peer_host, peer_port,
            self.ready_queue.get_queue_state, self._receive_transfer,
        )
        self._closing = Event()
        self._pending_times: dict[str, dict] = {}
        self._outgoing_transfers: dict[str, dict] = {}
        self._incoming_slots = 0
        self._active_p2p_check: str | None = None
        self._p2p_threads: list[Thread] = []
        self._p2p_failed = False
        self._p2p_error: Exception | None = None

    def get_statistics(self) -> dict:
        with self._state_lock:
            average = self.total_waiting_time / self.processing_count if self.processing_count else 0.0
            return {
                "throughput": len(self.storage),
                "success_count": len(self.storage),
                "failure_count": self.failure_count,
                "average_waiting_time": average,
                "p2p_event_count": len(self.p2p_events),
                "reassignment_count": len(self.reassignments),
                "total_execution_time": self.total_execution_time,
            }

    def log(self, event: str, status: str, message: str, clock=None) -> None:
        """Master가 확정한 시각으로 기존 로거에 기록한다."""
        if self.logger is not None:
            self.logger.log(self.clock if clock is None else clock, event, status, message)

    def create_message(self, kind: str, **data) -> dict:
        """새 논리 메시지의 ID와 공통 필드를 만든다."""
        if kind in {"P2P_TIME", "P2P_COST", "P2P_TRANSFER", "P2P_FAILURE"}:
            data["communication_ids"] = list(dict.fromkeys(data["communication_ids"]))
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
        peers = message["peers"]
        # 주소 검사는 P2P 쪽에서 한 번만 처리한다.
        self.p2p.set_peers(peers)
        self.p2p.start()
        self.log("INIT", "SUCCESS", f"P2P 서버 시작 {self.peer_host}:{self.peer_port}")
        return self.create_message("READY", request_id=message["message_id"])

    def _handle_task(self, message: dict) -> dict:
        """확인 대기 작업까지 포함해 수락 여부를 결정한다."""
        key, attempt = self._task_identity(message)
        value = message["value"]
        if type(value) is not int or not 1 <= value <= 100:
            raise ValueError("value는 1~100의 정수여야 합니다.")

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
        identity = (task.key, task.attempt)
        if task.failed_retry and identity not in self.reassignments:
            self.reassignments.add(identity)
            self.log("REASSIGN", "INFO", f"실패 재할당 접수 key={task.key} attempt={task.attempt}", enqueued_at)
        return self.create_message(
            "QUEUE_STATUS", request_id=message["message_id"],
            queue_size=size, queue_version=version,
        )

    def start_next_task(self) -> None:
        """처리 중인 작업이 없으면 PROCESS_START를 보내고 수신 반복으로 돌아간다."""
        if self.stopping or self._p2p_failed or not self.running or not self.ready or self.current_task is not None:
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
        if started_at < task.enqueued_at:
            raise ValueError("처리 시작 시각이 큐 진입 시각보다 빠릅니다.")
        waiting_time = task.accumulated_waiting_time + started_at - task.enqueued_at
        self.total_waiting_time += waiting_time
        self.processing_count += 1
        if not math.isclose(waiting_time, master_waiting_time, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("Master와 Worker의 대기시간이 일치하지 않습니다.")
        self.log("PROC", "INFO", f"처리 시작 key={task.key} waiting_time={waiting_time}", started_at)

        status = "SUCCESS" if self.rng.random() < 0.8 else "FAIL"
        if status == "SUCCESS":
            if task.key in self.storage and self.storage[task.key] != task.value:
                raise ValueError("같은 key에 다른 value가 이미 저장되어 있습니다.")
            self.storage[task.key] = task.value
        else:
            self.failure_count += 1
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
        pending["response"] = message.copy()
        pending["event"].set()

    def _receive_transfer(
        self, transfer_id: str, source_id: int, tasks: list[dict], transfer_message_id: str,
    ) -> tuple[bool, str]:
        """P2PNode 콜백: 공간을 확보하고 수신 시각을 받아 예약된 작업을 넣는다."""
        # P2PNode에서 검사한 작업 목록을 받는다.
        incoming = [WorkerTask(**item) for item in tasks]
        started_at = incoming[0].enqueued_at

        with self._state_lock:
            if self._closing.is_set():
                raise ConnectionClosed("Worker가 종료 중입니다.")
            with self.ready_queue._lock:
                needed = len(self.pending_tasks) + self._incoming_slots + len(incoming)
                if not self.ready_queue.has_capacity(needed):
                    return False, "전체 작업을 받을 Queue 공간이 부족합니다."
                # TIME_ACK 대기 중 Master 작업이 이 공간을 차지하지 못하게 한다.
                self._incoming_slots += len(incoming)

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
            for before, state in changes:
                self._report_p2p_queue(before, state, arrived_at)
            self.log("P2P_ACK", "INFO", f"id={transfer_id} 수신, Master 이전 확정 대기", arrived_at)
            for task in incoming:
                self.log("P2P_TRANSFER", "INFO",
                         f"id={transfer_id} source={source_id} target={self.worker_id} "
                         f"key={task.key} attempt={task.attempt} phase=RECEIVED "
                         f"started_at={started_at} arrived_at={arrived_at} "
                         f"prior_wait={task.accumulated_waiting_time}", arrived_at)
        return True, f"작업 {len(incoming)}개 수신 완료"

    def _handle_transfer_confirmed(self, message: dict) -> dict | None:
        """Master가 소유권을 확정한 이전만 예약 해제하고 한 번 집계한다."""
        transfer_id = message["transfer_id"]
        outgoing = self._outgoing_transfers.pop(transfer_id, None)
        if outgoing is not None:
            arrived_at = self._read_time(message, "new_enqueued_at")
            self.log("P2P_ACK", "SUCCESS", f"id={transfer_id} ACCEPTED, Master 이전 확정")
            for task in outgoing["tasks"]:
                self.log("P2P_TRANSFER", "SUCCESS",
                         f"id={transfer_id} source={self.worker_id} target={outgoing['target']} "
                         f"key={task.key} attempt={task.attempt} phase=SENT "
                         f"started_at={outgoing['started_at']} arrived_at={arrived_at} "
                         f"enqueued_at={task.enqueued_at} prior_wait={task.accumulated_waiting_time}")
            return None
        if transfer_id in self.p2p_events:
            return None

        with self.ready_queue._lock:
            before, _ = self.ready_queue.get_queue_state()
            if not self.ready_queue.cancel_transfer(transfer_id):
                raise ValueError("확정할 수신 예약이 없습니다.")
            size, version = self.ready_queue.get_queue_state()
        self._log_queue_change(before, size, self.clock)
        self.p2p_events.add(transfer_id)
        self.log("P2P_TRANSFER", "SUCCESS", f"id={transfer_id} 수신 작업 처리 가능")
        response = self.create_message(
            "QUEUE_STATUS", request_id=message["message_id"],
            queue_size=size, queue_version=version,
        )
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
        """점검 결과를 보고하고 다음 작업을 시작한다."""
        with self._state_lock:
            self._active_p2p_check = None
            if response["type"] == "P2P_FAILURE":
                self._p2p_failed = True
            self.log("P2P_CHECK", "INFO", f"REPORT {json.dumps(response, ensure_ascii=False)}")
            if not self._closing.is_set():
                self.send_message(response)
                if not self._p2p_failed:
                    self.start_next_task()

    def _handle_p2p_exception(self, error: Exception) -> None:
        """점검 스레드 오류를 수신 스레드에 전달하고 연결 대기를 깨운다."""
        with self._state_lock:
            if self._closing.is_set():
                return
            self._p2p_failed = True
            self._p2p_error = error
            sock = self.sock
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
        try:
            with self._state_lock:
                if self._closing.is_set():
                    return
                size, _ = self.ready_queue.get_queue_state()
                self.log("P2P_CHECK", "INFO", f"request={request_id} start_queue={size}")
                if size * 2 <= 15:
                    response = self.create_message(
                        "P2P_COST", request_id=request_id, communication_ids=[],
                        reason="BELOW_THRESHOLD",
                    )
                    self._finish_p2p_check(request_id, response)
                    return
                clock = self.clock
            target = self.p2p.find_transfer_target(size, clock)
            communication_ids = list(dict.fromkeys(target["communication_ids"]))
            target_id = target["target_worker_id"]
            self.log("P2P_CHECK", "INFO", f"request={request_id} peers={json.dumps(target, ensure_ascii=False)}")
            with self._state_lock:
                if self._closing.is_set():
                    return
                with self.ready_queue._lock:
                    before, _ = self.ready_queue.get_queue_state()
                    tasks = []
                    # 조회 중 일반 처리가 진행될 수 있으므로 예약 직전에 다시 검사한다.
                    if before * 2 > 15 and target_id is not None:
                        count = min(target["transfer_count"],
                                    max(0, (before - target["target_queue_size"]) // 2))
                        if count > 0:
                            tasks = self.ready_queue.reserve_for_transfer(transfer_id, count)
                    state = self.ready_queue.get_queue_state()
                if not tasks:
                    reason = ("BELOW_THRESHOLD_AFTER_QUERY" if before * 2 <= 15
                              else "NO_PEER" if not target["peer_queues"]
                              else "NO_QUEUE_DIFFERENCE" if target_id is None
                              else "NO_RESERVABLE_TASK")
                    response = self.create_message(
                        "P2P_COST", request_id=request_id, communication_ids=communication_ids,
                        reason=reason,
                    )
                    self.log("P2P_CHECK", "INFO", f"request={request_id} final_queue={before} reason={reason}")
                    self._finish_p2p_check(request_id, response)
                    return
                self._report_p2p_queue(before, state, self.clock)

            started_at = self._request_p2p_time(
                transfer_id, self.worker_id, target_id, "SEND", communication_ids,
            )
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
            communication_ids = list(dict.fromkeys(communication_ids + result["communication_ids"]))
            for _ in range(3):
                if result["status"] != "UNKNOWN" or self._closing.is_set():
                    break
                with self._state_lock:
                    clock = self.clock
                result = self.p2p.check_transfer(target_id, transfer_id, clock)
                communication_ids = list(dict.fromkeys(communication_ids + result["communication_ids"]))

            with self._state_lock:
                if self._closing.is_set():
                    return
                if result["status"] == "UNKNOWN":
                    reason = f"상태 조회 3회 모두 UNKNOWN: {result['reason']}"
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
                    self.p2p_events.add(transfer_id)
                    # Master 확정 통지 시 송신 로그에 사용할 정보만 보관.
                    self._outgoing_transfers[transfer_id] = {
                        "target": target_id, "tasks": tasks, "started_at": started_at,
                    }
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
                        reason="RECEIVER_REJECTED",
                    )
                if result["status"] != "ACCEPTED":
                    self.log("P2P_ACK", "INFO", f"id={transfer_id} {result['status']}: {result['reason']}")
                self._finish_p2p_check(request_id, response)
        except Exception as error:
            self._handle_p2p_exception(error)

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
        self.total_execution_time = total_time
        stats = self.get_statistics()
        self.stopping = True
        self.log("STOP", "INFO", f"종료 요청 work_completed_at={completed_at}")
        return self.create_message(
            "STOP_ACK", request_id=message["message_id"], stats=stats, stats_at=self.clock,
        )

    def handle_message(self, message: dict) -> None:
        """Master 메시지 처리와 P2P 스레드의 상태 변경이 겹치지 않게 한다."""
        with self._state_lock:
            self._handle_master_message(message)

    def _handle_master_message(self, message: dict) -> None:
        """Master 수신은 한 스레드만 담당하며 여기서는 TIME_ACK를 기다리지 않는다."""
        if message.get("sender") != "MASTER" or message.get("receiver") != f"WORKER{self.worker_id}":
            raise InvalidMessage("Master 메시지의 송수신 노드가 일치하지 않습니다.")
        message_id, kind = message["message_id"], message["type"]
        clock = self._read_time(message, "clock")

        # Master는 재전송하지 않으며, 같은 ID의 보고는 다시 처리하지 않는다.
        if message_id in self._seen_messages:
            return
        self.clock = clock

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
        elif kind == "FINAL_STATS":
            total_time = self._read_time(message, "total_execution_time")
            self.total_execution_time = total_time
            self.clock = total_time
            self.log("STAT", "INFO", f"stats_at={total_time} {self.get_statistics()}")
            self.running = False
            response = None
        else:
            self.log("INIT", "WARN", f"아직 지원하지 않는 메시지: {kind}")
            response = None

        if response is not None:
            self.send_message(response)
        self._seen_messages.add(message_id)
        if kind == "PEERS":
            self.ready = True
            self.log("INIT", "SUCCESS", "PEERS 저장 및 READY 전송 완료")
        elif kind == "PROCESS_ACK":
            self.current_task = None
            self.process_request_id = None
            self.processing_time = None
        elif kind == "STOP":
            self.log("STOP_ACK", "SUCCESS", "통계 응답 전송 완료, 최종 시간 대기")

        # 점검 스레드가 예약 대상을 고를 수 있도록 이 요청에서는 다음 작업을 꺼내지 않는다.
        if kind != "P2P_CHECK" and not self._p2p_failed:
            self.start_next_task()

    def run(self, timeout=60) -> None:
        """Master에 등록하고 STOP까지 메시지를 수신한다."""
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
                    self._handle_master_message(message)
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
