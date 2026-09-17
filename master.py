"""Master의 작업 생성, 분배, 결과 관리. 상태 변경은 메인 스레드에서만 수행."""

import argparse
import json
import queue
import random
import socket
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from logger import NodeLogger, initialize_log_files
from protocol import ConnectionClosed, InvalidMessage, JsonLineConnection


@dataclass
class Task:
    value: int
    attempt: int = 0
    state: str = "WAITING"
    worker_id: int | None = None
    failed_worker: int | None = None
    retry: bool = False


@dataclass
class Worker:
    host: str
    port: int
    ready: bool = False
    queue_size: int = 0
    queue_version: int = -1
    pending_key: str | None = None
    success: int = 0
    fail: int = 0
    rejected: int = 0
    reassignments: int = 0
    waiting_sum: float = 0.0
    p2p_sent: int = 0
    p2p_received: int = 0
    final_stats: dict = field(default_factory=dict)


class Master:
    def __init__(self, count=5000, seed=None):
        if not 1 <= count <= 65536:
            raise ValueError("작업 수는 1~65536이어야 합니다")
        rng = random.Random(seed)
        keys = rng.sample(range(65536), count)
        self.original = {f"{key:04x}": rng.randint(1, 100) for key in keys}
        self.tasks = {key: Task(value) for key, value in self.original.items()}
        self.new_tasks = deque(self.original)
        self.retry_tasks = deque()
        self.workers = {}
        self.completed = {}
        self.transfers = {}
        self.last_worker = 0

    def register_worker(self, worker_id, host, port):
        if type(worker_id) is not int or worker_id not in range(1, 5):
            raise ValueError("Worker ID는 1~4 정수여야 합니다")
        if worker_id in self.workers:
            raise ValueError("이미 연결된 Worker ID입니다")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("P2P 접속 주소가 필요합니다")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("P2P 포트가 올바르지 않습니다")
        self.workers[worker_id] = Worker(host, port)

    def set_ready(self, worker_id):
        self.workers[worker_id].ready = True

    def all_ready(self):
        return len(self.workers) == 4 and all(w.ready for w in self.workers.values())

    def update_queue(self, worker_id, size, version):
        if type(size) is not int or not 0 <= size <= 10:
            raise ValueError("대기 큐 크기는 0~10이어야 합니다")
        if type(version) is not int or version < 0:
            raise ValueError("큐 버전은 0 이상 정수여야 합니다")
        worker = self.workers[worker_id]
        if version > worker.queue_version:
            worker.queue_size = size
            worker.queue_version = version

    def select_worker(self, excluded=None):
        # 같은 큐 크기이면 마지막 배정 다음 Worker부터 선택.
        candidates = []
        for offset in range(1, 5):
            worker_id = (self.last_worker + offset - 1) % 4 + 1
            worker = self.workers.get(worker_id)
            if (worker is not None and worker.ready and worker_id != excluded
                    and worker.queue_size < 10 and worker.pending_key is None):
                candidates.append(worker_id)
        if not candidates:
            return None
        return min(candidates, key=lambda wid: self.workers[wid].queue_size)

    def next_assignment(self):
        if not self.all_ready():
            return None
        # 재시도가 대기 중이면 신규 작업보다 먼저 배정.
        queue = self.retry_tasks if self.retry_tasks else self.new_tasks
        if not queue:
            return None
        key = queue[0]
        task = self.tasks[key]
        worker_id = self.select_worker(task.failed_worker)
        if worker_id is None:
            return None
        queue.popleft()
        task.attempt += 1
        task.state = "SENT"
        task.worker_id = worker_id
        self.workers[worker_id].pending_key = key
        self.last_worker = worker_id
        return worker_id, {
            "key": key, "value": task.value,
            "attempt": task.attempt, "is_retry": task.retry,
        }

    def acknowledge(self, worker_id, key, attempt, accepted):
        if type(accepted) is not bool:
            raise ValueError("accepted는 bool이어야 합니다")
        task = self.tasks[key]
        if (task.attempt != attempt or task.worker_id != worker_id
                or task.state != "SENT"):
            return False
        worker = self.workers[worker_id]
        worker.pending_key = None
        if accepted:
            task.state = "QUEUED"
            if task.failed_worker is not None:
                worker.reassignments += 1
        else:
            worker.rejected += 1
            task.state = "WAITING"
            task.worker_id = None
            task.retry = True
            self.retry_tasks.append(key)
        return True

    def record_result(self, worker_id, key, attempt, value, status, waiting_time):
        task = self.tasks[key]
        # 과거 시도와 중복 결과는 완료 수와 통계에 반영하지 않음.
        if task.attempt != attempt or task.state in {"DONE", "WAITING"}:
            return False
        if task.worker_id != worker_id or task.state != "QUEUED":
            raise ValueError("작업 배정 또는 P2P 완료 보고가 먼저 필요합니다")
        if value != task.value or status not in {"SUCCESS", "FAIL"}:
            raise ValueError("작업 값 또는 결과 상태가 올바르지 않습니다")
        if not isinstance(waiting_time, (int, float)) or not 0 <= waiting_time < float("inf"):
            raise ValueError("대기시간은 유한한 0 이상 숫자여야 합니다")
        worker = self.workers[worker_id]
        worker.waiting_sum += waiting_time
        if status == "SUCCESS":
            worker.success += 1
            self.completed[key] = value
            task.state = "DONE"
        else:
            worker.fail += 1
            task.failed_worker = worker_id
            task.worker_id = None
            task.state = "WAITING"
            task.retry = True
            self.retry_tasks.append(key)
        return True

    def record_transfer(self, transfer_id, source, target, items):
        # 송신 Worker가 ACK를 받은 뒤, 결과 처리보다 먼저 반영할 완료 보고.
        if source == target or source not in self.workers or target not in self.workers:
            raise ValueError("이전 Worker 정보가 올바르지 않습니다")
        if not isinstance(transfer_id, str) or not transfer_id or not items:
            raise ValueError("이전 ID와 작업 목록이 필요합니다")
        signature = (source, target, tuple(sorted((item["key"], item["attempt"]) for item in items)))
        if transfer_id in self.transfers:
            if self.transfers[transfer_id] != signature:
                raise ValueError("같은 이전 ID에 다른 작업이 들어왔습니다")
            return False
        keys = [item["key"] for item in items]
        if len(set(keys)) != len(keys):
            raise ValueError("이전 목록에 중복 작업이 있습니다")
        for item in items:
            task = self.tasks[item["key"]]
            if (task.worker_id != source or task.attempt != item["attempt"]
                    or task.state != "QUEUED"):
                raise ValueError("이전할 수 없는 작업입니다")
        for key in keys:
            self.tasks[key].worker_id = target
        self.transfers[transfer_id] = signature
        self.workers[source].p2p_sent += 1
        self.workers[target].p2p_received += 1
        return True

    def is_complete(self):
        return (self.completed == self.original and not self.retry_tasks
                and not self.new_tasks
                and all(w.pending_key is None for w in self.workers.values()))

    def statistics(self):
        result = {}
        for worker_id, worker in sorted(self.workers.items()):
            attempts = worker.success + worker.fail
            result[worker_id] = {
                "processed": worker.success,
                "success": worker.success,
                "fail": worker.fail,
                "queue_rejects": worker.rejected,
                "avg_waiting_time": worker.waiting_sum / attempts if attempts else 0.0,
                "waiting_sum": worker.waiting_sum,
                "attempts": attempts,
                "reassignments": worker.reassignments,
                "p2p_sent": worker.p2p_sent,
                "p2p_received": worker.p2p_received,
            }
        return result


class MasterServer:
    """연결 검증용 서버. 가상 시간 진행은 규칙 확정 후 연결."""

    def __init__(self, master, logger, timeout=60):
        self.master = master
        self.logger = logger
        self.timeout = timeout
        self.inbox = queue.Queue()
        self.connections = {}
        self.threads = []
        self.message_number = 0
        self.stopping = False
        self.stop_acks = set()
        self.seen_messages = set()

    def now(self):
        # 연결 검증에서는 시각을 계산하지 않음.
        return 0

    def log(self, event, status, text):
        self.logger.log(self.now(), event, status, text)

    def send(self, worker_id, kind, **payload):
        self.message_number += 1
        message = {
            "type": kind, "message_id": f"master-{self.message_number}",
            "sender": "MASTER", "receiver": f"WORKER{worker_id}",
            "clock": self.now(), "payload": payload,
        }
        self.connections[worker_id].send(message)
        return message["message_id"]

    def receive_messages(self, worker_id, connection):
        # 수신 스레드는 메시지만 전달. 작업 상태는 메인 스레드에서 변경.
        try:
            while True:
                self.inbox.put((worker_id, connection.recv()))
        except (ConnectionClosed, InvalidMessage, OSError) as error:
            self.inbox.put((worker_id, error))

    def register_connections(self, server):
        while len(self.connections) < 4:
            sock, _ = server.accept()
            sock.settimeout(self.timeout)
            connection = JsonLineConnection(sock)
            try:
                message = connection.recv()
                if message.get("type") != "HELLO":
                    raise ValueError("첫 메시지는 HELLO여야 합니다")
                data = message["payload"]
                worker_id = data["worker_id"]
                self.master.register_worker(worker_id, data["peer_host"], data["peer_port"])
            except (KeyError, TypeError, ValueError, ConnectionClosed, InvalidMessage, OSError) as error:
                self.log("HELLO", "FAIL", str(error))
                sock.close()
                continue
            sock.settimeout(None)
            self.connections[worker_id] = connection
            self.log("HELLO", "SUCCESS", f"Worker{worker_id} 연결")
            thread = threading.Thread(target=self.receive_messages, args=(worker_id, connection))
            thread.start()
            self.threads.append(thread)

        peers = [{"worker_id": wid, "host": w.host, "port": w.port}
                 for wid, w in sorted(self.master.workers.items())]
        for worker_id in self.connections:
            self.send(worker_id, "PEERS", peers=peers)
        self.log("INIT", "INFO", "Worker 주소 공유 완료, READY 대기")

    def handle_message(self, worker_id, message):
        if isinstance(message, Exception):
            if worker_id in self.stop_acks:
                return
            raise RuntimeError(f"Worker{worker_id} 연결 오류: {message}")
        if message.get("sender") != f"WORKER{worker_id}" or message.get("receiver") != "MASTER":
            raise ValueError("메시지 송수신 노드가 일치하지 않습니다")
        message_id = message.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise ValueError("message_id가 필요합니다")
        identity = (worker_id, message_id)
        if identity in self.seen_messages:
            return
        kind = message["type"]
        data = message["payload"]
        if not isinstance(data, dict):
            raise ValueError("payload는 객체여야 합니다")
        worker = self.master.workers[worker_id]

        if kind == "READY":
            self.master.set_ready(worker_id)
            self.log("INIT", "SUCCESS", f"Worker{worker_id} 준비 완료")
        elif kind == "QUEUE_STATUS":
            self.master.update_queue(worker_id, data["queue_size"], data["queue_version"])
            self.log("QUEUE_STATUS", "INFO", f"Worker{worker_id} queue={worker.queue_size}")
        elif kind == "TASK_ACK":
            self.master.update_queue(worker_id, data["queue_size"], data["queue_version"])
            if self.master.acknowledge(worker_id, data["key"], data["attempt"], data["accepted"]):
                status = "SUCCESS" if data["accepted"] else "FAIL"
                self.log("TASK_ACK", status, f"Worker{worker_id} key={data['key']}")
        elif kind == "RESULT":
            self.master.update_queue(worker_id, data["queue_size"], data["queue_version"])
            changed = self.master.record_result(
                worker_id, data["key"], data["attempt"], data["value"],
                data["status"], data["waiting_time"],
            )
            if changed:
                self.log("RESULT", data["status"], f"Worker{worker_id} key={data['key']} attempt={data['attempt']}")
                if data["status"] == "FAIL":
                    self.log("REASSIGN", "INFO", f"key={data['key']} 우선 재할당 대기")
        elif kind == "TRANSFER_RESULT":
            if worker_id != data["source"]:
                raise ValueError("P2P 완료 보고는 송신 Worker에서 전송해야 합니다")
            changed = self.master.record_transfer(
                data["transfer_id"], data["source"], data["target"], data["items"],
            )
            if changed:
                self.log("P2P_TRANSFER", "SUCCESS", f"id={data['transfer_id']} {data['source']} -> {data['target']}")
            self.send(data["target"], "TRANSFER_RECORDED", transfer_id=data["transfer_id"])
        elif kind == "STOP_ACK":
            if not self.stopping:
                raise ValueError("종료 요청 전 STOP_ACK를 받았습니다")
            stats = data["stats"]
            if (not isinstance(stats, dict) or stats.get("success") != worker.success
                    or stats.get("fail") != worker.fail):
                raise ValueError("Worker 최종 성공·실패 통계가 Master와 다릅니다")
            worker.final_stats = stats
            self.stop_acks.add(worker_id)
            self.log("STOP_ACK", "SUCCESS", f"Worker{worker_id} {json.dumps(worker.final_stats, ensure_ascii=False)}")
        else:
            raise ValueError(f"알 수 없는 메시지: {kind}")
        self.seen_messages.add(identity)

    def dispatch(self):
        while not self.stopping:
            assignment = self.master.next_assignment()
            if assignment is None:
                break
            worker_id, task = assignment
            self.send(worker_id, "TASK", **task)
            self.log("TASK", "INFO", f"Worker{worker_id} key={task['key']} attempt={task['attempt']}")

    def write_statistics(self):
        for key, value in sorted(self.master.completed.items()):
            self.log("STAT", "INFO", f"KV {key}={value}")
        stats = self.master.statistics()
        for worker_id, values in stats.items():
            self.log("STAT", "INFO", f"Worker{worker_id} {json.dumps(values, ensure_ascii=False)}")
        attempts = sum(w.success + w.fail for w in self.master.workers.values())
        waiting = sum(w.waiting_sum for w in self.master.workers.values())
        summary = {
            "success": len(self.master.completed),
            "fail": sum(w.fail for w in self.master.workers.values()),
            "reassignments": sum(w.reassignments for w in self.master.workers.values()),
            "p2p_events": len(self.master.transfers),
            "avg_waiting_time": waiting / attempts if attempts else 0,
            "execution_time": None,
        }
        self.log("STAT", "INFO", json.dumps(summary, ensure_ascii=False))

    def run(self, host="0.0.0.0", port=5000):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((host, port))
                server.listen(4)
                server.settimeout(self.timeout)
                self.log("INIT", "INFO", f"{host}:{server.getsockname()[1]} 접속 대기")
                print(f"Master listening on {host}:{server.getsockname()[1]}", flush=True)
                self.register_connections(server)
                while len(self.stop_acks) < 4:
                    try:
                        worker_id, message = self.inbox.get(timeout=self.timeout)
                    except queue.Empty as error:
                        raise RuntimeError("Worker 메시지 대기 시간 초과") from error
                    self.handle_message(worker_id, message)
                    self.dispatch()
                    if not self.stopping and self.master.is_complete():
                        self.stopping = True
                        for wid in self.connections:
                            self.send(wid, "STOP", completed=len(self.master.completed))
                        self.log("STOP", "INFO", "전체 작업 완료, Worker 종료 응답 대기")
                self.write_statistics()
                self.log("STOP", "SUCCESS", "모든 Worker 종료 응답 확인")
        finally:
            # 공통 프로토콜에 close 메서드가 없어 원래 소켓을 정리.
            for connection in self.connections.values():
                try:
                    connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.sock.close()
            for thread in self.threads:
                thread.join()


def main():
    parser = argparse.ArgumentParser(description="Master 연결·분배 구현")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--log-dir", default="logs/master")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--connection-test", action="store_true")
    args = parser.parse_args()
    if not args.connection_test:
        parser.error("가상 시간 규칙 연동 전입니다. 연결 검증은 --connection-test로 실행하세요")
    if not 0 <= args.port <= 65535 or args.timeout <= 0:
        parser.error("포트 또는 대기 시간이 올바르지 않습니다")
    master = Master(args.count, args.seed)
    # Worker와 다른 폴더를 사용하여 기존 Worker 로그 초기화를 방지.
    initialize_log_files(Path(args.log_dir))
    with NodeLogger("Master", args.log_dir) as logger:
        logger.log(0, "INIT", "WARN", "연결 검증 모드: 가상 시계 미연동, 제출용 실행 아님")
        app = MasterServer(master, logger, timeout=args.timeout)
        try:
            app.run(args.host, args.port)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, KeyboardInterrupt) as error:
            logger.log(app.now(), "STOP", "FAIL", f"미완료 종료: {error}")
            raise SystemExit(1) from error


if __name__ == "__main__":
    main()
