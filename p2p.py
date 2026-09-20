"""Worker 사이의 큐 조회와 작업 이전 통신을 담당한다."""

from __future__ import annotations

import json
import math
import socket
import threading

from protocol import ConnectionClosed, InvalidMessage, JsonLineConnection


MAX_QUEUE_SIZE = 10
TRANSFER_STATUSES = {"ACCEPTED", "REJECTED", "UNKNOWN"}


class P2PError(Exception):
    """P2P 메시지나 응답 형식이 잘못된 경우."""


def _read_worker_name(value, field_name):
    """WORKER1 형식의 이름에서 Worker ID를 읽는다."""
    if not isinstance(value, str) or not value.startswith("WORKER"):
        raise P2PError(f"{field_name}는 WORKER1~WORKER4 형식이어야 합니다")

    worker_text = value[6:]
    if not worker_text.isdigit():
        raise P2PError(f"{field_name}는 WORKER1~WORKER4 형식이어야 합니다")

    worker_id = int(worker_text)
    if worker_id not in range(1, 5):
        raise P2PError(f"{field_name}의 Worker ID는 1~4여야 합니다")
    return worker_id


def _read_clock(value):
    """가상 시각이 0 이상의 유한한 숫자인지 확인한다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise P2PError("clock은 숫자여야 합니다")
    if not math.isfinite(value) or value < 0:
        raise P2PError("clock은 0 이상의 유한한 숫자여야 합니다")
    return float(value)


def _read_transfer_id(value):
    """전송 ID를 확인한다."""
    if not isinstance(value, str) or not value.strip():
        raise P2PError("transfer_id는 비어 있지 않은 문자열이어야 합니다")
    return value


def _read_queue_state(queue_size, queue_version):
    """큐 크기와 버전을 확인한다."""
    if type(queue_size) is not int or not 0 <= queue_size <= MAX_QUEUE_SIZE:
        raise P2PError("queue_size는 0~10의 정수여야 합니다")
    if type(queue_version) is not int or queue_version < 0:
        raise P2PError("queue_version은 0 이상의 정수여야 합니다")
    return queue_size, queue_version


def clean_tasks(tasks):
    """P2P로 보낼 작업 목록을 검사하고 필요한 필드만 복사한다."""
    if not isinstance(tasks, list) or not tasks:
        raise P2PError("tasks는 비어 있지 않은 list여야 합니다")

    cleaned = []
    identities = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise P2PError("각 작업은 dict여야 합니다")

        key = task.get("key")
        if (
            not isinstance(key, str)
            or len(key) != 4
            or any(character not in "0123456789abcdefABCDEF" for character in key)
        ):
            raise P2PError("key는 4자리 16진수 문자열이어야 합니다")
        key = key.upper()

        value = task.get("value")
        if type(value) is not int or not 1 <= value <= 100:
            raise P2PError("value는 1~100의 정수여야 합니다")

        attempt = task.get("attempt")
        if type(attempt) is not int or attempt < 1:
            raise P2PError("attempt는 1 이상의 정수여야 합니다")

        enqueued_at = _read_clock(task.get("enqueued_at"))
        waiting_time = task.get("accumulated_waiting_time", 0.0)
        if isinstance(waiting_time, bool) or not isinstance(waiting_time, (int, float)):
            raise P2PError("accumulated_waiting_time은 숫자여야 합니다")
        if not math.isfinite(waiting_time) or waiting_time < 0:
            raise P2PError("accumulated_waiting_time은 0 이상의 유한한 숫자여야 합니다")

        failed_retry = task.get("failed_retry", False)
        if type(failed_retry) is not bool:
            raise P2PError("failed_retry는 bool이어야 합니다")

        identity = (key, attempt)
        if identity in identities:
            raise P2PError("같은 Key와 시도 번호의 작업이 중복되었습니다")
        identities.add(identity)

        cleaned.append(
            {
                "key": key,
                "value": value,
                "attempt": attempt,
                "enqueued_at": enqueued_at,
                "accumulated_waiting_time": float(waiting_time),
                "failed_retry": failed_retry,
            }
        )

    return cleaned


class P2PNode:
    """Worker 하나의 P2P 서버와 다른 Worker로의 요청을 관리한다."""

    def __init__(
        self,
        worker_id,
        host,
        port,
        queue_state_provider,
        transfer_receiver,
        timeout=5,
    ):
        if type(worker_id) is not int or worker_id not in range(1, 5):
            raise ValueError("worker_id는 1~4의 정수여야 합니다")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host는 비어 있지 않은 문자열이어야 합니다")
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port는 0~65535의 정수여야 합니다")
        if not callable(queue_state_provider) or not callable(transfer_receiver):
            raise TypeError("queue_state_provider와 transfer_receiver는 함수여야 합니다")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout은 숫자여야 합니다")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout은 유한한 양수여야 합니다")

        self.worker_id = worker_id
        self.host = host
        self.port = port
        self.queue_state_provider = queue_state_provider
        self.transfer_receiver = transfer_receiver
        self.timeout = float(timeout)

        self.peers = {}
        self.received_transfers = {}
        self.message_number = 0
        self.server_socket = None
        self.accept_thread = None
        self.client_sockets = set()
        self.client_threads = set()

        self.running = threading.Event()
        self.message_lock = threading.Lock()
        self.peer_lock = threading.Lock()
        self.transfer_lock = threading.Lock()
        self.client_lock = threading.Lock()

    def set_peers(self, peers):
        """Master가 보낸 Worker 주소 목록을 검사해 저장한다."""
        if not isinstance(peers, list):
            raise ValueError("peers는 list여야 합니다")

        checked = {}
        for peer in peers:
            if not isinstance(peer, dict):
                raise ValueError("각 peer는 dict여야 합니다")
            peer_id = peer.get("worker_id")
            host = peer.get("host")
            port = peer.get("port")
            if type(peer_id) is not int or peer_id not in range(1, 5):
                raise ValueError("peer worker_id는 1~4의 정수여야 합니다")
            if peer_id in checked:
                raise ValueError("peer worker_id가 중복되었습니다")
            if not isinstance(host, str) or not host.strip():
                raise ValueError("peer host는 비어 있지 않은 문자열이어야 합니다")
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("peer port는 1~65535의 정수여야 합니다")
            checked[peer_id] = {"host": host, "port": port}

        if set(checked) != {1, 2, 3, 4}:
            raise ValueError("Worker 1~4의 주소가 모두 필요합니다")

        with self.peer_lock:
            self.peers = checked

    def start(self):
        """P2P 요청을 받을 TCP 서버를 시작한다."""
        if self.running.is_set():
            raise RuntimeError("P2P 서버가 이미 실행 중입니다")

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen()
            server.settimeout(0.5)
        except Exception:
            server.close()
            raise

        self.server_socket = server
        self.port = server.getsockname()[1]
        self.running.set()
        self.accept_thread = threading.Thread(
            target=self._accept_loop,
            name=f"Worker{self.worker_id}-P2P",
        )
        self.accept_thread.start()

    def stop(self):
        """서버 소켓과 실행 중인 수신 스레드를 정리한다."""
        self.running.clear()

        server = self.server_socket
        self.server_socket = None
        if server is not None:
            try:
                server.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            server.close()

        if self.accept_thread is not None:
            self.accept_thread.join(timeout=self.timeout + 1)
            self.accept_thread = None

        # accept 스레드가 끝난 뒤 목록을 읽어 종료 중 새 연결도 빠뜨리지 않는다.
        with self.client_lock:
            sockets = list(self.client_sockets)
            threads = list(self.client_threads)
        for client in sockets:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()
        for thread in threads:
            thread.join(timeout=self.timeout + 1)

    def find_transfer_target(self, source_queue_size, clock):
        """다른 Worker의 큐를 조회해 이전 대상과 작업 수를 정한다."""
        if type(source_queue_size) is not int or not 0 <= source_queue_size <= 10:
            raise ValueError("source_queue_size는 0~10의 정수여야 합니다")
        clock = _read_clock(clock)

        communication_ids = []
        states = []
        with self.peer_lock:
            peer_ids = sorted(self.peers)

        for peer_id in peer_ids:
            if peer_id == self.worker_id:
                continue
            state, message_ids = self._query_queue(peer_id, clock)
            communication_ids.extend(message_ids)
            if state is not None:
                states.append(state)

        result = {
            "target_worker_id": None,
            "target_queue_size": None,
            "target_queue_version": None,
            "transfer_count": 0,
            "communication_ids": communication_ids,
        }
        if not states:
            return result

        target = min(states, key=lambda item: (item["queue_size"], item["worker_id"]))
        difference = source_queue_size - target["queue_size"]
        transfer_count = min(difference // 2, MAX_QUEUE_SIZE - target["queue_size"])
        if transfer_count <= 0:
            return result

        result.update(
            {
                "target_worker_id": target["worker_id"],
                "target_queue_size": target["queue_size"],
                "target_queue_version": target["queue_version"],
                "transfer_count": transfer_count,
            }
        )
        return result

    def send_transfer(self, target_id, transfer_id, tasks, clock):
        """작업을 대상 Worker에 보내고 수신 결과를 반환한다."""
        transfer_id = _read_transfer_id(transfer_id)
        cleaned_tasks = clean_tasks(tasks)
        response, message_ids = self._request(
            target_id,
            "P2P_TRANSFER",
            _read_clock(clock),
            transfer_id=transfer_id,
            tasks=cleaned_tasks,
        )
        if response is None:
            return {
                "status": "UNKNOWN",
                "reason": "P2P_ACK를 받지 못했습니다",
                "communication_ids": message_ids,
            }

        self._check_response(response, "P2P_ACK", transfer_id)
        return {
            "status": response["status"],
            "reason": response["reason"],
            "communication_ids": message_ids,
        }

    def check_transfer(self, target_id, transfer_id, clock):
        """대상 Worker가 이전 요청을 받았는지 다시 확인한다."""
        transfer_id = _read_transfer_id(transfer_id)
        response, message_ids = self._request(
            target_id,
            "P2P_STATUS",
            _read_clock(clock),
            transfer_id=transfer_id,
        )
        if response is None:
            return {
                "status": "UNKNOWN",
                "reason": "이전 상태 응답을 받지 못했습니다",
                "communication_ids": message_ids,
            }

        self._check_response(response, "P2P_STATUS_ACK", transfer_id)
        return {
            "status": response["status"],
            "reason": response["reason"],
            "communication_ids": message_ids,
        }

    def _query_queue(self, target_id, clock):
        response, message_ids = self._request(target_id, "P2P_QUEUE_QUERY", clock)
        if response is None:
            return None, message_ids
        self._check_response(response, "P2P_QUEUE_ACK")
        queue_size, queue_version = _read_queue_state(
            response.get("queue_size"), response.get("queue_version")
        )
        return {
            "worker_id": target_id,
            "queue_size": queue_size,
            "queue_version": queue_version,
        }, message_ids

    def _request(self, target_id, kind, clock, **data):
        """다른 Worker에 요청 하나를 보내고 응답 하나를 받는다."""
        peer = self._get_peer(target_id)
        request = self._make_message(kind, target_id, clock, **data)
        message_ids = [request["message_id"]]

        try:
            with socket.create_connection(
                (peer["host"], peer["port"]), self.timeout
            ) as sock:
                sock.settimeout(self.timeout)
                connection = JsonLineConnection(sock)
                connection.send(request)
                response = connection.recv()
        except (OSError, ConnectionClosed, InvalidMessage):
            return None, message_ids

        self._validate_common(response, expected_sender=target_id)
        if response.get("request_id") != request["message_id"]:
            raise P2PError("응답의 request_id가 요청 message_id와 다릅니다")
        message_ids.append(response["message_id"])

        if response["type"] == "P2P_ERROR":
            raise P2PError(response.get("reason", "상대 Worker가 요청을 거부했습니다"))
        return response, message_ids

    def _get_peer(self, target_id):
        if type(target_id) is not int or target_id not in range(1, 5):
            raise ValueError("target_id는 1~4의 정수여야 합니다")
        if target_id == self.worker_id:
            raise ValueError("자기 자신에게 P2P 요청을 보낼 수 없습니다")
        with self.peer_lock:
            peer = self.peers.get(target_id)
            if peer is None:
                raise ValueError(f"Worker{target_id} 주소가 등록되지 않았습니다")
            return peer.copy()

    def _make_message(self, kind, target_id, clock, **data):
        with self.message_lock:
            self.message_number += 1
            message_id = f"p2p-{self.worker_id}-{self.message_number}"
        return {
            **data,
            "type": kind,
            "sender": f"WORKER{self.worker_id}",
            "receiver": f"WORKER{target_id}",
            "message_id": message_id,
            "clock": clock,
        }

    def _accept_loop(self):
        server = self.server_socket
        while self.running.is_set():
            try:
                client, _ = server.accept()
                client.settimeout(self.timeout)
            except socket.timeout:
                continue
            except OSError:
                break

            thread = threading.Thread(
                target=self._handle_client,
                args=(client,),
                name=f"Worker{self.worker_id}-P2P-client",
            )
            with self.client_lock:
                self.client_sockets.add(client)
                self.client_threads.add(thread)
            thread.start()

    def _handle_client(self, client):
        request = None
        try:
            connection = JsonLineConnection(client)
            request = connection.recv()
            response = self._handle_request(request)
            connection.send(response)
        except (P2PError, KeyError, TypeError, ValueError) as error:
            response = self._error_response(request, str(error))
            if response is not None:
                try:
                    JsonLineConnection(client).send(response)
                except OSError:
                    pass
        except (ConnectionClosed, InvalidMessage, OSError):
            pass
        finally:
            client.close()
            current = threading.current_thread()
            with self.client_lock:
                self.client_sockets.discard(client)
                self.client_threads.discard(current)

    def _handle_request(self, request):
        sender_id = self._validate_common(request)
        kind = request["type"]
        if kind == "P2P_QUEUE_QUERY":
            queue_size, queue_version = self.queue_state_provider()
            queue_size, queue_version = _read_queue_state(queue_size, queue_version)
            return self._make_response(
                "P2P_QUEUE_ACK",
                sender_id,
                request,
                queue_size=queue_size,
                queue_version=queue_version,
            )
        if kind == "P2P_TRANSFER":
            return self._receive_transfer(sender_id, request)
        if kind == "P2P_STATUS":
            return self._transfer_status(sender_id, request)
        raise P2PError(f"지원하지 않는 P2P 메시지입니다: {kind}")

    def _receive_transfer(self, sender_id, request):
        transfer_id = _read_transfer_id(request.get("transfer_id"))
        tasks = clean_tasks(request.get("tasks"))
        signature = json.dumps(tasks, ensure_ascii=False, sort_keys=True)

        with self.transfer_lock:
            previous = self.received_transfers.get(transfer_id)
            if previous is not None:
                if previous["signature"] != signature:
                    status = "REJECTED"
                    reason = "같은 transfer_id에 다른 작업이 전달되었습니다"
                else:
                    status = previous["status"]
                    reason = previous["reason"]
            else:
                result = self.transfer_receiver(transfer_id, sender_id, tasks)
                if (
                    not isinstance(result, tuple)
                    or len(result) != 2
                    or type(result[0]) is not bool
                ):
                    raise P2PError("transfer_receiver는 (bool, reason)을 반환해야 합니다")
                accepted, reason = result
                reason = str(reason)
                status = "ACCEPTED" if accepted else "REJECTED"
                self.received_transfers[transfer_id] = {
                    "signature": signature,
                    "status": status,
                    "reason": reason,
                }

        return self._make_response(
            "P2P_ACK",
            sender_id,
            request,
            transfer_id=transfer_id,
            status=status,
            reason=reason,
        )

    def _transfer_status(self, sender_id, request):
        transfer_id = _read_transfer_id(request.get("transfer_id"))
        with self.transfer_lock:
            previous = self.received_transfers.get(transfer_id)
            if previous is None:
                status = "UNKNOWN"
                reason = "해당 transfer_id를 받은 기록이 없습니다"
            else:
                status = previous["status"]
                reason = previous["reason"]
        return self._make_response(
            "P2P_STATUS_ACK",
            sender_id,
            request,
            transfer_id=transfer_id,
            status=status,
            reason=reason,
        )

    def _make_response(self, kind, target_id, request, **data):
        return self._make_message(
            kind,
            target_id,
            request["clock"],
            request_id=request["message_id"],
            **data,
        )

    def _error_response(self, request, reason):
        if not isinstance(request, dict):
            return None
        try:
            sender_id = _read_worker_name(request.get("sender"), "sender")
            message_id = request.get("message_id")
            clock = _read_clock(request.get("clock"))
            if not isinstance(message_id, str) or not message_id.strip():
                return None
            return self._make_message(
                "P2P_ERROR",
                sender_id,
                clock,
                request_id=message_id,
                reason=reason,
            )
        except P2PError:
            return None

    def _validate_common(self, message, expected_sender=None):
        if not isinstance(message, dict):
            raise P2PError("P2P 메시지는 dict여야 합니다")
        kind = message.get("type")
        if not isinstance(kind, str) or not kind.strip():
            raise P2PError("메시지 type이 필요합니다")
        message_id = message.get("message_id")
        if not isinstance(message_id, str) or not message_id.strip():
            raise P2PError("message_id가 필요합니다")

        sender_id = _read_worker_name(message.get("sender"), "sender")
        receiver_id = _read_worker_name(message.get("receiver"), "receiver")
        if sender_id == self.worker_id:
            raise P2PError("자기 자신이 보낸 메시지는 받을 수 없습니다")
        if receiver_id != self.worker_id:
            raise P2PError("메시지 receiver가 현재 Worker와 다릅니다")
        if expected_sender is not None and sender_id != expected_sender:
            raise P2PError("응답 sender가 요청 대상 Worker와 다릅니다")
        _read_clock(message.get("clock"))
        return sender_id

    @staticmethod
    def _check_response(response, expected_type, transfer_id=None):
        if response.get("type") != expected_type:
            raise P2PError(f"{expected_type} 응답이 필요합니다")
        if transfer_id is not None and response.get("transfer_id") != transfer_id:
            raise P2PError("응답의 transfer_id가 요청과 다릅니다")
        if expected_type in {"P2P_ACK", "P2P_STATUS_ACK"}:
            if response.get("status") not in TRANSFER_STATUSES:
                raise P2PError("P2P 응답 상태가 올바르지 않습니다")
            if not isinstance(response.get("reason"), str):
                raise P2PError("P2P 응답 reason은 문자열이어야 합니다")


# Worker 연결 예제
#
#   def get_queue_state():
#       return worker.ready_queue.get_queue_state()
#
#   def receive_tasks(transfer_id, source_id, tasks):
#       # 여기에서 WorkerReadyQueue의 공간을 다시 확인하고 수신 작업을 예약한다.
#       return True, f"Worker{source_id} 작업 {len(tasks)}개 수신"
#
#   p2p = P2PNode(
#       worker.worker_id,
#       worker.peer_host,
#       worker.peer_port,
#       get_queue_state,
#       receive_tasks,
#   )
#   p2p.set_peers(worker.peers)
#   p2p.start()
#
# P2P_CHECK 처리 예제
#
#   target = p2p.find_transfer_target(worker.ready_queue.get_queue_size(), worker.clock)
#   if target["transfer_count"] == 0:
#       # communication_ids를 P2P_COST에 넣어 Master에 보고한다.
#       pass
#
# 작업 이전 예제
#
#   result = p2p.send_transfer(target_id, transfer_id, tasks, worker.clock)
#   if result["status"] == "UNKNOWN":
#       # ACK가 없다고 예약을 취소하지 않고 상대의 수신 상태를 확인한다.
#       result = p2p.check_transfer(target_id, transfer_id, worker.clock)
#   if result["status"] == "ACCEPTED":
#       # Master의 시간 확인과 TRANSFER_CONFIRMED 이후 Queue 이전을 확정한다.
#       pass
#   elif result["status"] == "REJECTED":
#       # 확실한 거절일 때만 기존 Queue의 예약을 해제한다.
#       pass
