"""Master 실행: python master.py --host 0.0.0.0 --port 5000

메시지는 type, sender, receiver, message_id, clock과 작업 정보를 같은 dict에 저장.
HELLO: worker_id, peer_host, peer_port / READY: 초기화 완료
TASK_ACK: key, attempt, accepted, queue_size, queue_version
RESULT: key, value, attempt, status, processing_time, waiting_time, queue_size, queue_version
P2P_TRANSFER: transfer_id, source, target, tasks(key/attempt 목록), communication_count
P2P_COST: 이전 없이 끝난 조회의 communication_count(중복 보고 금지)
STOP_ACK: stats(WorkerStats.snapshot 결과)
가상 시간은 송수신 1초와 처리시간을 더하는 초안. 병렬 시각 동기화는 별도 합의 필요.
전체 수행시간은 초기화 0부터 마지막 고유 작업 성공까지. 종료 통신은 별도 로그 시각에 반영.
"""

import argparse
import json
import math
import queue
import random
import socket
import threading
from collections import deque

from logger import NodeLogger, initialize_log_files
from protocol import ConnectionClosed, InvalidMessage, JsonLineConnection


class Master:
    def __init__(self, count=5000, seed=None):
        if not 1 <= count <= 65536:
            raise ValueError("작업 수는 1~65536 범위입니다")
        rng = random.Random(seed)
        self.original = {f"{key:04X}": rng.randint(1, 100)
                         for key in rng.sample(range(65536), count)}
        self.tasks = {key: {"value": value, "attempt": 0, "state": "WAITING",
                            "owner": None, "failed_worker": None}
                      for key, value in self.original.items()}
        self.new_tasks = deque(self.original)
        self.retry_tasks = deque()
        self.completed = {}
        self.workers = {}
        self.inbox = queue.Queue()
        self.threads = []
        self.transfers = {}
        self.early_results = {}
        self.seen_messages = set()
        self.clock = 0.0
        self.last_worker = 0
        self.message_number = 0
        self.stopping = False
        self.finished_at = None
        self.logger = None

    def add_time(self, seconds):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("가상 시간은 유한한 0 이상 숫자여야 합니다")
        self.clock += seconds

    def log(self, event, status, message):
        if self.logger is not None:
            self.logger.log(round(self.clock, 3), event, status, message)

    def send(self, worker_id, kind, **data):
        self.message_number += 1
        message = {"type": kind, "sender": "MASTER", "receiver": f"WORKER{worker_id}",
                   "message_id": f"master-{self.message_number}", "clock": self.clock, **data}
        self.workers[worker_id]["connection"].send(message)
        self.add_time(1)

    def receive_loop(self, worker_id, connection):
        # 수신 스레드는 메시지만 전달. 상태 변경은 메인 스레드에서 처리.
        try:
            while True:
                self.inbox.put((worker_id, connection.recv()))
        except (ConnectionClosed, InvalidMessage, OSError) as error:
            self.inbox.put((worker_id, error))

    def register_worker(self, message, connection):
        worker_id = message["worker_id"]
        if type(worker_id) is not int or worker_id not in range(1, 5) or worker_id in self.workers:
            raise ValueError("Worker ID 중복 또는 범위 오류")
        if not isinstance(message["peer_host"], str) or not message["peer_host"].strip():
            raise ValueError("P2P 주소가 필요합니다")
        if type(message["peer_port"]) is not int or not 1 <= message["peer_port"] <= 65535:
            raise ValueError("P2P 포트 오류")
        self.workers[worker_id] = {
            "connection": connection, "host": message["peer_host"], "port": message["peer_port"],
            "ready": False, "queue_size": 0, "queue_version": -1, "pending": None,
            "success": 0, "fail": 0, "waiting": 0.0, "reassignments": 0,
            "p2p_events": 0, "stopped": False,
        }
        self.log("HELLO", "SUCCESS", f"Worker{worker_id} 연결")
        return worker_id

    def accept_workers(self, server, timeout):
        while len(self.workers) < 4:
            sock, _ = server.accept()
            sock.settimeout(timeout)
            connection = JsonLineConnection(sock)
            try:
                message = connection.recv()
                self.add_time(1)
                if message.get("type") != "HELLO":
                    raise ValueError("첫 메시지는 HELLO가 필요합니다")
                worker_id = self.register_worker(message, connection)
            except (KeyError, TypeError, ValueError, ConnectionClosed, InvalidMessage, OSError) as error:
                self.log("HELLO", "FAIL", str(error))
                sock.close()
                continue
            thread = threading.Thread(target=self.receive_loop, args=(worker_id, connection))
            thread.start()
            self.threads.append(thread)
        peers = [{"worker_id": wid, "host": w["host"], "port": w["port"]}
                 for wid, w in sorted(self.workers.items())]
        for worker_id in self.workers:
            self.send(worker_id, "PEERS", peers=peers)
        self.log("INIT", "INFO", "P2P 주소 공유 완료, READY 대기")

    def update_queue(self, worker_id, message):
        size, version = message["queue_size"], message["queue_version"]
        if type(size) is not int or not 0 <= size <= 10 or type(version) is not int or version < 0:
            raise ValueError("큐 크기 또는 버전 오류")
        worker = self.workers[worker_id]
        if version > worker["queue_version"]:
            worker["queue_size"], worker["queue_version"] = size, version

    def choose_worker(self, excluded):
        candidates = []
        for offset in range(1, 5):
            worker_id = (self.last_worker + offset - 1) % 4 + 1
            worker = self.workers[worker_id]
            if worker_id != excluded and worker["queue_size"] < 10 and worker["pending"] is None:
                candidates.append(worker_id)
        return min(candidates, key=lambda wid: self.workers[wid]["queue_size"]) if candidates else None

    def distribute(self):
        if len(self.workers) != 4 or not all(w["ready"] for w in self.workers.values()):
            return
        while self.retry_tasks or self.new_tasks:
            waiting = self.retry_tasks if self.retry_tasks else self.new_tasks
            key = waiting[0]
            task = self.tasks[key]
            worker_id = self.choose_worker(task["failed_worker"])
            if worker_id is None:
                return
            waiting.popleft()
            task["attempt"] += 1
            task["owner"], task["state"] = worker_id, "SENT"
            self.workers[worker_id]["pending"] = key
            self.last_worker = worker_id
            self.send(worker_id, "TASK", key=key, value=task["value"], attempt=task["attempt"],
                      is_retry=task["attempt"] > 1, failed_retry=task["failed_worker"] is not None)
            self.log("TASK", "INFO", f"key={key} attempt={task['attempt']} -> Worker{worker_id}")

    def task_ack(self, worker_id, message):
        self.update_queue(worker_id, message)
        task = self.tasks[message["key"]]
        if (task["owner"] != worker_id or task["attempt"] != message["attempt"]
                or task["state"] != "SENT"):
            return
        if type(message["accepted"]) is not bool:
            raise ValueError("accepted는 bool이어야 합니다")
        self.workers[worker_id]["pending"] = None
        if message["accepted"]:
            task["state"] = "ACCEPTED"
            if task["failed_worker"] is not None:
                self.workers[worker_id]["reassignments"] += 1
        else:
            task["state"], task["owner"] = "WAITING", None
            self.retry_tasks.append(message["key"])
        self.log("TASK_ACK", "SUCCESS" if message["accepted"] else "FAIL",
                 f"Worker{worker_id} key={message['key']}")

    def task_result(self, worker_id, message):
        key = message["key"]
        task = self.tasks[key]
        if task["attempt"] != message["attempt"] or task["state"] in {"DONE", "WAITING"}:
            return
        if task["owner"] != worker_id:
            # P2P 완료 보고보다 수신 Worker 결과가 먼저 도착한 경우 보관.
            self.early_results.setdefault((key, message["attempt"], worker_id), message)
            return
        if task["state"] != "ACCEPTED":
            raise ValueError("RESULT 전에 TASK_ACK가 필요합니다")
        if message["value"] != task["value"] or message["status"] not in {"SUCCESS", "FAIL"}:
            raise ValueError("결과 값 또는 상태 오류")
        duration, wait = message["processing_time"], message["waiting_time"]
        if (type(duration) not in (int, float) or not 1 <= duration <= 3
                or type(wait) not in (int, float) or not math.isfinite(wait) or wait < 0):
            raise ValueError("처리시간 또는 대기시간 오류")
        self.add_time(duration)
        worker = self.workers[worker_id]
        worker["waiting"] += wait
        if message["status"] == "SUCCESS":
            task["state"] = "DONE"
            self.completed[key] = task["value"]
            worker["success"] += 1
        else:
            task["state"], task["owner"], task["failed_worker"] = "WAITING", None, worker_id
            worker["fail"] += 1
            self.retry_tasks.append(key)
            self.log("REASSIGN", "INFO", f"key={key} 재할당 대기")
        self.log("RESULT", message["status"], f"Worker{worker_id} key={key} attempt={task['attempt']}")

    def transfer_result(self, worker_id, message):
        source, target = message["source"], message["target"]
        transfer_id, items = message["transfer_id"], message["tasks"]
        if worker_id != source or source == target or target not in self.workers:
            raise ValueError("P2P 송수신 Worker 오류")
        signature = (source, target, tuple(sorted((item["key"], item["attempt"]) for item in items)))
        if transfer_id in self.transfers:
            if self.transfers[transfer_id] != signature:
                raise ValueError("동일 이전 ID의 내용이 다릅니다")
            return
        if not items or len({item["key"] for item in items}) != len(items):
            raise ValueError("P2P 작업 목록 오류")
        for item in items:
            task = self.tasks[item["key"]]
            if task["owner"] != source or task["attempt"] != item["attempt"] or task["state"] != "ACCEPTED":
                raise ValueError("P2P 이전 대상 불일치")
        count = message["communication_count"]
        if type(count) is not int or count < 2:
            raise ValueError("P2P 전송·ACK를 포함한 편도 통신 횟수가 필요합니다")
        self.add_time(count)
        self.transfers[transfer_id] = signature
        self.workers[source]["p2p_events"] += 1
        self.workers[target]["p2p_events"] += 1
        self.log("P2P_TRANSFER", "SUCCESS", f"id={transfer_id} Worker{source} -> Worker{target}")
        for item in items:
            self.tasks[item["key"]]["owner"] = target
            pending = self.early_results.pop((item["key"], item["attempt"], target), None)
            if pending is not None:
                self.task_result(target, pending)

    def handle_message(self, worker_id, message):
        worker = self.workers[worker_id]
        if isinstance(message, Exception):
            if worker["stopped"]:
                return
            raise RuntimeError(f"Worker{worker_id} 연결 종료: {message}")
        if message.get("sender") != f"WORKER{worker_id}" or message.get("receiver") != "MASTER":
            raise ValueError("메시지 송수신 노드 불일치")
        identity = (worker_id, message["message_id"])
        self.add_time(1)
        if identity in self.seen_messages:
            return
        kind = message["type"]
        if kind == "READY":
            worker["ready"] = True
            self.log("INIT", "SUCCESS", f"Worker{worker_id} 준비 완료")
        elif kind == "QUEUE_STATUS":
            self.update_queue(worker_id, message)
            self.log("QUEUE_STATUS", "INFO", f"Worker{worker_id} queue={worker['queue_size']}")
        elif kind == "TASK_ACK":
            self.task_ack(worker_id, message)
        elif kind == "RESULT":
            self.update_queue(worker_id, message)
            self.task_result(worker_id, message)
        elif kind == "P2P_TRANSFER":
            self.transfer_result(worker_id, message)
        elif kind == "P2P_COST":
            count = message["communication_count"]
            if type(count) is not int or count < 1:
                raise ValueError("P2P 편도 통신 횟수 오류")
            self.add_time(count)
            self.log("P2P_TRANSFER", "INFO", f"Worker{worker_id} 조회 통신={count}, 이전 없음")
        elif kind == "STOP_ACK":
            stats = message["stats"]
            if (not self.stopping or stats["success_count"] != worker["success"]
                    or stats["failure_count"] != worker["fail"]):
                raise ValueError("종료 시점 또는 Worker 통계 불일치")
            worker["stopped"] = True
            self.log("STOP_ACK", "SUCCESS", f"Worker{worker_id} {json.dumps(stats, ensure_ascii=False)}")
        else:
            raise ValueError(f"알 수 없는 메시지: {kind}")
        self.seen_messages.add(identity)

    def write_statistics(self):
        attempts = waiting = failures = reassignments = 0
        for key, value in sorted(self.completed.items()):
            self.log("STAT", "INFO", f"KV {key}={value}")
        for worker_id, worker in sorted(self.workers.items()):
            count = worker["success"] + worker["fail"]
            stats = {"throughput": worker["success"], "success_count": worker["success"],
                     "failure_count": worker["fail"], "average_waiting_time": worker["waiting"] / count if count else 0,
                     "p2p_event_count": worker["p2p_events"], "reassignment_count": worker["reassignments"],
                     "total_execution_time": self.finished_at}
            self.log("STAT", "INFO", f"Worker{worker_id} {json.dumps(stats)}")
            attempts += count
            waiting += worker["waiting"]
            failures += worker["fail"]
            reassignments += worker["reassignments"]
        self.log("STAT", "INFO", json.dumps({"success": len(self.completed), "fail": failures,
                 "average_waiting_time": waiting / attempts if attempts else 0,
                 "p2p_events": len(self.transfers), "reassignments": reassignments,
                 "total_execution_time": self.finished_at}))

    def run(self, host, port, log_dir, timeout=60):
        initialize_log_files(log_dir)
        self.logger = NodeLogger("Master", log_dir)
        try:
            self.log("INIT", "INFO", f"KV {len(self.original)}개 생성, 시간 모델=단순 누적 초안")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((host, port))
                server.listen(4)
                server.settimeout(timeout)
                print(f"Master {host}:{server.getsockname()[1]} 연결 대기", flush=True)
                self.accept_workers(server, timeout)
                while not all(w["stopped"] for w in self.workers.values()):
                    worker_id, message = self.inbox.get(timeout=timeout)
                    self.handle_message(worker_id, message)
                    if not self.stopping:
                        self.distribute()
                        if self.completed == self.original and not self.early_results:
                            self.stopping = True
                            self.finished_at = self.clock
                            for wid in self.workers:
                                self.send(wid, "STOP", total_execution_time=self.finished_at)
                            self.log("STOP", "INFO", "전체 작업 완료, 종료 응답 대기")
                self.write_statistics()
                self.log("STOP", "SUCCESS", "정상 종료")
        except Exception as error:
            self.log("STOP", "FAIL", f"미완료 종료: {error}")
            raise
        finally:
            for worker in self.workers.values():
                sock = worker["connection"].sock
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
            for thread in self.threads:
                thread.join()
            self.logger.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Master 서버")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--log-dir", default="logs/master")
    args = parser.parse_args()
    Master(args.count, args.seed).run(args.host, args.port, args.log_dir)
