"""Master 실행: python master.py --host 0.0.0.0 --port 5000

메시지는 type, sender, receiver, message_id, clock과 작업 정보를 같은 dict에 저장.
HELLO: worker_id, peer_host, peer_port / READY: 초기화 완료
TASK_ACK: key, attempt, accepted, queue_size, queue_version
  수락 후 TASK_CONFIRMED의 enqueued_at으로 WorkerTask 생성 시각 확정.
  큐 추가 후 QUEUE_STATUS.request_id에 TASK_CONFIRMED.message_id 포함.
  해당 보고 전까지 Master는 배정 작업의 큐 자리를 예약한 상태로 유지.
PROCESS_START: key, attempt, processing_time, queue_size, queue_version
  PROCESS_ACK의 started_at으로 record_processing_start 호출 후 처리.
  finished_at은 처리 비용까지 누적한 시각. RESULT에서 같은 처리시간·대기시간 보고.
RESULT: key, value, attempt, status, processing_time, waiting_time, queue_size, queue_version
P2P_CHECK: Master의 점검 요청. 이전 여부와 관계없이 아래 두 보고 중 하나로 응답.
P2P_TIME: transfer_id, source, target, phase(SEND/RECV), communication_ids.
  각 경계에서 이미 끝난 P2P 편도 통신 ID 보고 후 TIME_ACK 대기.
  SEND의 event_at과 RECV의 event_at을 for_p2p_transfer에 전달.
  Worker 간 작업 전송에는 기존 enqueued_at·accumulated_waiting_time도 포함.
P2P_TRANSFER: request_id(P2P_CHECK ID), transfer_id, source, target,
  tasks(key/attempt 목록), communication_ids(실제 P2P 편도 메시지의 고유 ID 목록).
  대상 Worker는 TRANSFER_CONFIRMED 수신 후 처리 시작. P2P 수신은 재할당 집계 제외.
P2P_COST: request_id(P2P_CHECK ID), communication_ids, transfer_id(예약 취소 시).
  ACK 미수신만으로 취소 금지. 수신 거절이 확정된 경우에만 취소 보고.
P2P_FAILURE: request_id(P2P_CHECK ID), transfer_id, source, target, reason, communication_ids.
  최초 UNKNOWN 이후 상태 조회 3회 모두 UNKNOWN이면 보고. 예약 유지, 전체 실패 종료.
STOP_ACK: request_id(STOP ID), stats(WorkerStats.snapshot 결과), stats_at(STOP의 clock).
  Worker는 STOP.clock을 통계 기준 시간으로 저장. Master는 모든 종료 응답까지 집계.
응답의 request_id는 원래 요청 ID. queue_version은 큐 변경마다 증가하는 정수.
clock은 Master가 편도 비용을 반영한 시각. Worker는 별도 시계 증가 금지.
같은 보고 재처리는 같은 ID 사용. 별도 실제 전송은 새 ID 사용.
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
        self.rng = rng
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
        self.seen_messages = set()
        self.peer_messages = set()
        self.transfer_times = {}
        self.clock = 0.0
        self.last_worker = 0
        self.message_number = 0
        self.stopping = False
        self.finished_at = None
        self.completed_at = None
        self.logger = None

    def add_time(self, seconds):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("가상 시간은 유한한 0 이상 숫자여야 합니다")
        self.clock += seconds
        # 점검은 로컬 계산. 점검 자체를 통신으로 만들면 시간이 끝없이 증가한다.
        for worker in self.workers.values():
            while worker["next_check"] is not None and worker["next_check"] <= self.clock:
                worker["check_due"] = True
                worker["next_check"] += self.rng.randint(1, 3)

    def log(self, event, status, message):
        if self.logger is not None:
            self.logger.log(round(self.clock, 3), event, status, message)

    def send(self, worker_id, kind, **data):
        self.message_number += 1
        self.add_time(1)
        message = {"type": kind, "sender": "MASTER", "receiver": f"WORKER{worker_id}",
                   "message_id": f"master-{self.message_number}", "clock": self.clock, **data}
        self.workers[worker_id]["connection"].send(message)
        event = {"PEERS": "INIT", "TASK_CONFIRMED": "TASK_ACK", "PROCESS_ACK": "PROC",
                 "P2P_CHECK": "P2P_TRANSFER", "TIME_ACK": "P2P_TRANSFER",
                 "TRANSFER_CONFIRMED": "P2P_TRANSFER"}.get(kind, kind)
        self.log(event, "INFO", f"SEND {json.dumps(message, ensure_ascii=False)}")
        return message

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
            "ready": False, "queue_size": 0, "queue_version": -1, "pending": {},
            "success": 0, "fail": 0, "waiting": 0.0, "reassignments": 0,
            "p2p_events": 0, "stopped": False,
            "active": None, "next_check": None, "check_due": False,
            "check_request": None, "stop_request": None, "stats_at": None,
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
        # 수락 ACK만으로 자리를 풀면 확정 전 작업이 큐 크기에서 빠진다.
        request_id = message.get("request_id")
        if request_id is not None:
            for key, confirmed_id in list(worker["pending"].items()):
                if confirmed_id == request_id:
                    del worker["pending"][key]

    def queue_load(self, worker_id):
        worker = self.workers[worker_id]
        return worker["queue_size"] + len(worker["pending"])

    def choose_worker(self, excluded):
        candidates = []
        for offset in range(1, 5):
            worker_id = (self.last_worker + offset - 1) % 4 + 1
            if worker_id != excluded and self.queue_load(worker_id) < 10:
                candidates.append(worker_id)
        return min(candidates, key=self.queue_load) if candidates else None

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
            self.workers[worker_id]["pending"][key] = None
            self.last_worker = worker_id
            task["waiting_time"] = 0.0
            request = self.send(worker_id, "TASK", key=key, value=task["value"], attempt=task["attempt"],
                      is_retry=task["attempt"] > 1, failed_retry=task["failed_worker"] is not None)
            task["request_id"] = request["message_id"]
            self.log("TASK", "INFO", f"key={key} attempt={task['attempt']} -> Worker{worker_id}")

    def task_ack(self, worker_id, message):
        self.update_queue(worker_id, message)
        task = self.tasks[message["key"]]
        if (task["owner"] != worker_id or task["attempt"] != message["attempt"]
                or task["state"] != "SENT"):
            return
        if type(message["accepted"]) is not bool:
            raise ValueError("accepted는 bool이어야 합니다")
        if message["request_id"] != task["request_id"]:
            raise ValueError("TASK_ACK 요청 ID 불일치")
        if message["accepted"]:
            task["state"] = "ACCEPTED"
            task["enqueued_at"] = self.clock
            if task["failed_worker"] is not None:
                self.workers[worker_id]["reassignments"] += 1
            confirmed = self.send(worker_id, "TASK_CONFIRMED", request_id=message["message_id"],
                      key=message["key"], attempt=task["attempt"], enqueued_at=task["enqueued_at"])
            self.workers[worker_id]["pending"][message["key"]] = confirmed["message_id"]
        else:
            self.workers[worker_id]["pending"].pop(message["key"], None)
            task["state"], task["owner"] = "WAITING", None
            self.retry_tasks.append(message["key"])
        self.log("TASK_ACK", "SUCCESS" if message["accepted"] else "FAIL",
                 f"Worker{worker_id} key={message['key']}")

    def processing_start(self, worker_id, message):
        task = self.tasks[message["key"]]
        worker = self.workers[worker_id]
        if (task["owner"] != worker_id or task["attempt"] != message["attempt"]
                or task["state"] != "ACCEPTED" or worker["active"] is not None):
            raise ValueError("처리 시작 대상 또는 순서 오류")
        duration = message["processing_time"]
        if type(duration) not in (int, float) or not 1 <= duration <= 3:
            raise ValueError("처리시간은 1~3초여야 합니다")
        self.update_queue(worker_id, message)
        task["waiting_time"] += self.clock - task["enqueued_at"]
        task["started_at"] = self.clock
        task["processing_time"] = duration
        task["state"] = "PROCESSING"
        worker["active"] = message["key"]
        self.log("PROC", "INFO", f"Worker{worker_id} key={message['key']} 처리 시작")
        self.add_time(duration)
        task["finished_at"] = self.clock
        self.send(worker_id, "PROCESS_ACK", request_id=message["message_id"],
                  key=message["key"], attempt=task["attempt"], started_at=task["started_at"],
                  finished_at=task["finished_at"], waiting_time=task["waiting_time"])

    def task_result(self, worker_id, message):
        key = message["key"]
        task = self.tasks[key]
        if task["attempt"] != message["attempt"] or task["state"] in {"DONE", "WAITING"}:
            return
        if task["owner"] != worker_id:
            raise ValueError("결과를 보낸 Worker가 현재 작업 소유자가 아닙니다")
        if task["state"] != "PROCESSING":
            raise ValueError("RESULT 전에 PROCESS_START가 필요합니다")
        if message["value"] != task["value"] or message["status"] not in {"SUCCESS", "FAIL"}:
            raise ValueError("결과 값 또는 상태 오류")
        duration, wait = message["processing_time"], message["waiting_time"]
        if (type(duration) not in (int, float) or not 1 <= duration <= 3
                or type(wait) not in (int, float) or not math.isfinite(wait) or wait < 0):
            raise ValueError("처리시간 또는 대기시간 오류")
        if duration != task["processing_time"] or not math.isclose(wait, task["waiting_time"], abs_tol=1e-9):
            raise ValueError("Master와 Worker 처리시간 또는 대기시간 불일치")
        worker = self.workers[worker_id]
        worker["active"] = None
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

    def check_load(self):
        if self.stopping or len(self.workers) != 4 or not all(w["ready"] for w in self.workers.values()):
            return
        for worker_id, worker in self.workers.items():
            if not worker["check_due"]:
                continue
            worker["check_due"] = False
            if worker["queue_size"] * 2 > 15 and worker["check_request"] is None:
                request = self.send(worker_id, "P2P_CHECK")
                worker["check_request"] = request["message_id"]

    def transfer_time(self, worker_id, message):
        transfer_id = message["transfer_id"]
        source, target = message["source"], message["target"]
        if not isinstance(transfer_id, str) or not transfer_id or source == target or target not in self.workers:
            raise ValueError("P2P 이전 정보 오류")
        self.peer_cost(message)
        if message["phase"] == "SEND":
            if worker_id != source or self.workers[source]["check_request"] is None:
                raise ValueError("P2P 점검 요청 없이 이전 시작")
            if transfer_id in self.transfer_times or transfer_id in self.transfers:
                raise ValueError("이전 ID 재사용")
            self.transfer_times[transfer_id] = {
                "source": source, "target": target, "started_at": self.clock,
                "request_id": self.workers[source]["check_request"],
                "arrived_at": None,
            }
        elif message["phase"] == "RECV":
            transfer = self.transfer_times[transfer_id]
            if (worker_id != target or source != transfer["source"] or target != transfer["target"]
                    or transfer["arrived_at"] is not None):
                raise ValueError("P2P 수신 시각 요청 불일치")
            transfer["arrived_at"] = self.clock
        else:
            raise ValueError("P2P 시각 종류 오류")
        self.send(worker_id, "TIME_ACK", request_id=message["message_id"],
                  transfer_id=transfer_id, phase=message["phase"], event_at=self.clock)

    def peer_cost(self, message, minimum=0):
        ids = message["communication_ids"]
        if (not isinstance(ids, list) or len(ids) < minimum
                or any(not isinstance(item, str) or not item for item in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("P2P 통신 ID 목록 오류")
        self.add_time(len(set(ids) - self.peer_messages))
        self.peer_messages.update(ids)

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
        worker = self.workers[worker_id]
        if message["request_id"] != worker["check_request"]:
            raise ValueError("P2P 점검 요청 ID 불일치")
        times = self.transfer_times[transfer_id]
        if times["source"] != source or times["target"] != target or times["arrived_at"] is None:
            raise ValueError("P2P 송수신 시각 확인 필요")
        if not items or len({item["key"] for item in items}) != len(items):
            raise ValueError("P2P 작업 목록 오류")
        for item in items:
            task = self.tasks[item["key"]]
            if task["owner"] != source or task["attempt"] != item["attempt"] or task["state"] != "ACCEPTED":
                raise ValueError("P2P 이전 대상 불일치")
            if task["enqueued_at"] > times["started_at"]:
                raise ValueError("큐 진입보다 이전 시작이 빠릅니다")
        self.peer_cost(message, minimum=2)
        self.transfers[transfer_id] = signature
        self.workers[source]["p2p_events"] += 1
        self.workers[target]["p2p_events"] += 1
        self.log("P2P_TRANSFER", "SUCCESS", f"id={transfer_id} Worker{source} -> Worker{target}")
        for item in items:
            task = self.tasks[item["key"]]
            task["waiting_time"] += times["started_at"] - task["enqueued_at"]
            task["enqueued_at"] = times["arrived_at"]
            task["owner"] = target
        self.send(target, "TRANSFER_CONFIRMED", request_id=message["message_id"],
                  transfer_id=transfer_id, tasks=items, transfer_started_at=times["started_at"],
                  new_enqueued_at=times["arrived_at"])
        worker["check_request"] = None
        del self.transfer_times[transfer_id]

    def transfer_failure(self, worker_id, message):
        worker = self.workers[worker_id]
        request_id, transfer_id = message["request_id"], message["transfer_id"]
        source, target, reason = message["source"], message["target"], message["reason"]
        if (self.stopping or not isinstance(request_id, str) or not request_id.strip()
                or request_id != worker["check_request"]):
            raise ValueError("P2P_FAILURE 점검 요청 ID 또는 시점 오류")
        if (type(source) is not int or type(target) is not int or source != worker_id
                or source == target or target not in self.workers):
            raise ValueError("P2P_FAILURE 송수신 Worker 불일치")
        if not isinstance(transfer_id, str) or not transfer_id.strip():
            raise ValueError("P2P_FAILURE 이전 ID 오류")
        transfer = self.transfer_times.get(transfer_id)
        if (transfer is None or transfer_id in self.transfers
                or transfer["source"] != source or transfer["target"] != target
                or transfer["request_id"] != request_id):
            raise ValueError("P2P_FAILURE 진행 중 이전 정보 불일치")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("P2P_FAILURE 실패 이유가 필요합니다")
        self.peer_cost(message)
        self.log("P2P_TRANSFER", "FAIL", f"P2P_FAILURE {json.dumps(message, ensure_ascii=False)}")
        # 수신 여부가 불명확하므로 작업 소유권·예약 기록은 그대로 보존한다.
        worker["check_request"] = None
        self.stopping = True
        raise RuntimeError(f"P2P_FAILURE id={transfer_id} Worker{source} -> Worker{target}: {reason}")

    def worker_statistics(self, worker_id, total_time):
        worker = self.workers[worker_id]
        count = worker["success"] + worker["fail"]
        return {"throughput": worker["success"], "success_count": worker["success"],
                "failure_count": worker["fail"],
                "average_waiting_time": worker["waiting"] / count if count else 0,
                "p2p_event_count": worker["p2p_events"], "reassignment_count": worker["reassignments"],
                "total_execution_time": total_time}

    def stop_ack(self, worker_id, message):
        worker = self.workers[worker_id]
        if not self.stopping or message["request_id"] != worker["stop_request"]:
            raise ValueError("종료 시점 또는 요청 ID 불일치")
        stats_at = message["stats_at"]
        if type(stats_at) not in (int, float) or stats_at != worker["stats_at"]:
            raise ValueError("Worker 통계 기준 시각 불일치")
        expected = self.worker_statistics(worker_id, stats_at)
        stats = message["stats"]
        for name, value in expected.items():
            actual = stats[name]
            if (type(actual) not in (int, float) or not math.isfinite(actual)
                    or not math.isclose(actual, value, rel_tol=1e-9, abs_tol=1e-9)):
                raise ValueError(f"Worker{worker_id} 통계 불일치: {name}")
        worker["stopped"] = True
        self.log("STOP_ACK", "SUCCESS", f"Worker{worker_id} stats_at={stats_at} {json.dumps(stats)}")

    def handle_message(self, worker_id, message):
        worker = self.workers[worker_id]
        if isinstance(message, Exception):
            if worker["stopped"]:
                return
            raise RuntimeError(f"Worker{worker_id} 연결 종료: {message}")
        if message.get("sender") != f"WORKER{worker_id}" or message.get("receiver") != "MASTER":
            raise ValueError("메시지 송수신 노드 불일치")
        identity = (worker_id, message["message_id"])
        if identity in self.seen_messages:
            return
        self.add_time(1)
        kind = message["type"]
        if kind == "READY":
            worker["ready"] = True
            if all(w["ready"] for w in self.workers.values()):
                for item in self.workers.values():
                    if item["next_check"] is None:
                        item["next_check"] = self.clock + self.rng.randint(1, 3)
            self.log("INIT", "SUCCESS", f"Worker{worker_id} 준비 완료")
        elif kind == "QUEUE_STATUS":
            self.update_queue(worker_id, message)
            self.log("QUEUE_STATUS", "INFO", f"Worker{worker_id} queue={worker['queue_size']}")
        elif kind == "TASK_ACK":
            self.task_ack(worker_id, message)
        elif kind == "PROCESS_START":
            self.processing_start(worker_id, message)
        elif kind == "RESULT":
            self.update_queue(worker_id, message)
            self.task_result(worker_id, message)
        elif kind == "P2P_TRANSFER":
            self.transfer_result(worker_id, message)
        elif kind == "P2P_TIME":
            self.transfer_time(worker_id, message)
        elif kind == "P2P_FAILURE":
            self.transfer_failure(worker_id, message)
        elif kind == "P2P_COST":
            if message["request_id"] != worker["check_request"]:
                raise ValueError("P2P 점검 요청 ID 불일치")
            transfer_id = message.get("transfer_id")
            if transfer_id is not None:
                transfer = self.transfer_times[transfer_id]
                if transfer["source"] != worker_id or transfer["arrived_at"] is not None:
                    raise ValueError("이미 수신된 작업은 취소할 수 없습니다")
                del self.transfer_times[transfer_id]
            self.peer_cost(message)
            worker["check_request"] = None
            self.log("P2P_TRANSFER", "INFO", f"Worker{worker_id} 점검 완료, 이전 없음")
        elif kind == "STOP_ACK":
            self.stop_ack(worker_id, message)
        else:
            raise ValueError(f"알 수 없는 메시지: {kind}")
        self.seen_messages.add(identity)

    def write_statistics(self):
        attempts = waiting = failures = reassignments = 0
        for key, value in sorted(self.completed.items()):
            self.log("STAT", "INFO", f"KV {key}={value}")
        for worker_id, worker in sorted(self.workers.items()):
            count = worker["success"] + worker["fail"]
            stats = self.worker_statistics(worker_id, self.finished_at)
            self.log("STAT", "INFO", f"Worker{worker_id} {json.dumps(stats)}")
            attempts += count
            waiting += worker["waiting"]
            failures += worker["fail"]
            reassignments += worker["reassignments"]
        self.log("STAT", "INFO", json.dumps({"success": len(self.completed), "fail": failures,
                 "average_waiting_time": waiting / attempts if attempts else 0,
                 "p2p_events": len(self.transfers), "reassignments": reassignments,
                 "work_completed_at": self.completed_at,
                 "total_execution_time": self.finished_at}))

    def finish_if_ready(self):
        if self.stopping or self.completed != self.original:
            return
        if self.completed_at is None:
            self.completed_at = self.clock
        if self.transfer_times or any(w["check_request"] is not None for w in self.workers.values()):
            return
        self.stopping = True
        for worker_id, worker in self.workers.items():
            # 종료 요청마다 기준 시각 저장. 이후 종료 통신은 Master 최종 통계에 반영.
            request = self.send(worker_id, "STOP", work_completed_at=self.completed_at,
                                total_execution_time=self.clock + 1)
            worker["stop_request"] = request["message_id"]
            worker["stats_at"] = request["clock"]
        self.log("STOP", "INFO", "전체 작업 완료, 종료 응답 대기")

    def run(self, host, port, log_dir, timeout=60):
        initialize_log_files(log_dir)
        self.logger = NodeLogger("Master", log_dir)
        try:
            self.log("INIT", "INFO", f"KV {len(self.original)}개 생성, 시간 모델=전역 비용 누적")
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
                        self.finish_if_ready()
                        if self.completed != self.original:
                            self.check_load()
                self.finished_at = self.clock
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
