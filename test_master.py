"""Master 로직과 실제 TCP 연결 검증. 테스트 Worker는 제출용 Worker가 아님."""

import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from master import Master
from protocol import JsonLineConnection


def ready_master(count=20):
    master = Master(count, seed=7)
    for worker_id in range(1, 5):
        master.register_worker(worker_id, "127.0.0.1", 6000 + worker_id)
        master.set_ready(worker_id)
    return master


class MasterTests(unittest.TestCase):
    def test_data_and_ready(self):
        master = Master(seed=1)
        self.assertEqual(len(master.original), 5000)
        self.assertTrue(all(len(k) == 4 and 0 <= int(k, 16) <= 65535 for k in master.original))
        self.assertTrue(all(1 <= v <= 100 for v in master.original.values()))
        self.assertIsNone(master.next_assignment())

    def test_round_robin_and_full_queues(self):
        master = ready_master()
        self.assertEqual([master.next_assignment()[0] for _ in range(4)], [1, 2, 3, 4])
        self.assertIsNone(master.next_assignment())  # 수신 확인 전 추가 배정 방지
        master = ready_master()
        for worker_id in range(1, 5):
            master.update_queue(worker_id, 10, 1)
        self.assertIsNone(master.next_assignment())
        master.update_queue(3, 2, 2)
        self.assertEqual(master.next_assignment()[0], 3)

    def test_retries_duplicates_and_values(self):
        master = ready_master()
        worker_id, task = master.next_assignment()
        key = task["key"]
        for _ in range(2):
            master.acknowledge(worker_id, key, task["attempt"], True)
            with self.assertRaises(ValueError):
                master.record_result(worker_id, key, task["attempt"], 999, "SUCCESS", 0)
            master.record_result(worker_id, key, task["attempt"], task["value"], "FAIL", 2)
            self.assertFalse(master.record_result(worker_id, key, task["attempt"], task["value"], "FAIL", 2))
            next_worker, next_task = master.next_assignment()
            self.assertEqual(next_task["key"], key)  # 신규 작업보다 먼저
            self.assertNotEqual(next_worker, worker_id)
            self.assertEqual(next_task["attempt"], task["attempt"] + 1)
            worker_id, task = next_worker, next_task
        master.acknowledge(worker_id, key, task["attempt"], True)
        self.assertTrue(master.record_result(worker_id, key, task["attempt"], task["value"], "SUCCESS", 1))
        self.assertFalse(master.record_result(worker_id, key, task["attempt"], task["value"], "SUCCESS", 1))
        self.assertEqual(sum(w.fail for w in master.workers.values()), 2)
        self.assertEqual(sum(w.success for w in master.workers.values()), 1)
        self.assertEqual(sum(w.reassignments for w in master.workers.values()), 2)

    def test_rejection_and_old_queue_report(self):
        master = ready_master()
        wid, task = master.next_assignment()
        master.update_queue(wid, 10, 5)
        master.update_queue(wid, 0, 4)
        self.assertEqual(master.workers[wid].queue_size, 10)
        master.acknowledge(wid, task["key"], task["attempt"], False)
        next_wid, retry = master.next_assignment()
        self.assertNotEqual(wid, next_wid)
        self.assertEqual(task["key"], retry["key"])
        self.assertEqual(sum(w.fail for w in master.workers.values()), 0)

    def test_transfer(self):
        master = ready_master(1)
        wid, task = master.next_assignment()
        master.acknowledge(wid, task["key"], task["attempt"], True)
        items = [{"key": task["key"], "attempt": task["attempt"]}]
        self.assertTrue(master.record_transfer("transfer-1", wid, 2, items))
        self.assertFalse(master.record_transfer("transfer-1", wid, 2, items))
        master.record_result(2, task["key"], task["attempt"], task["value"], "SUCCESS", 3)
        self.assertTrue(master.is_complete())
        self.assertEqual(master.workers[2].success, 1)
        self.assertEqual(len(master.transfers), 1)

    def test_tcp_5000_tasks(self):
        errors = []
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.Popen(
                [sys.executable, "master.py", "--connection-test", "--host", "127.0.0.1",
                 "--port", "0", "--count", "5000", "--seed", "1", "--timeout", "15",
                 "--log-dir", directory],
                cwd=Path(__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8",
            )
            threads = []
            try:
                line = process.stdout.readline()
                self.assertIn("Master listening", line)
                port = int(line.strip().rsplit(":", 1)[1])

                def worker(worker_id):
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=15) as sock:
                            connection = JsonLineConnection(sock)
                            number = 0
                            version = 0
                            success = fail = 0

                            def send(kind, **payload):
                                nonlocal number
                                number += 1
                                connection.send({
                                    "type": kind, "message_id": f"w{worker_id}-{number}",
                                    "sender": f"WORKER{worker_id}", "receiver": "MASTER",
                                    "clock": 0, "payload": payload,
                                })

                            send("HELLO", worker_id=worker_id, peer_host="127.0.0.1", peer_port=6000 + worker_id)
                            self.assertEqual(connection.recv()["type"], "PEERS")
                            send("READY")
                            while True:
                                message = connection.recv()
                                if message["type"] == "STOP":
                                    send("STOP_ACK", stats={"success": success, "fail": fail})
                                    return
                                self.assertEqual(message["type"], "TASK")
                                task = message["payload"]
                                version += 1
                                send("TASK_ACK", key=task["key"], attempt=task["attempt"], accepted=True,
                                     reply_to=message["message_id"], queue_size=0, queue_version=version)
                                # 일부 작업을 두 번 실패시켜 재재할당까지 확인.
                                failed = task["key"].endswith("0") and task["attempt"] <= 2
                                fail += int(failed)
                                success += int(not failed)
                                version += 1
                                send("RESULT", key=task["key"], value=task["value"], attempt=task["attempt"],
                                     status="FAIL" if failed else "SUCCESS", waiting_time=1,
                                     queue_size=0, queue_version=version)
                    except Exception as error:
                        errors.append(error)

                for worker_id in range(1, 5):
                    thread = threading.Thread(target=worker, args=(worker_id,))
                    thread.start()
                    threads.append(thread)
                stdout, stderr = process.communicate(timeout=90)
                for thread in threads:
                    thread.join(timeout=20)
                self.assertFalse(any(t.is_alive() for t in threads))
                self.assertEqual(errors, [])
                self.assertEqual(process.returncode, 0, stdout + stderr)
                log = (Path(directory) / "Master.txt").read_text(encoding="utf-8")
                self.assertEqual(log.count("| STAT | INFO | KV "), 5000)
                summary_line = next(line for line in log.splitlines() if '| STAT | INFO | {"success"' in line)
                summary = json.loads(summary_line.split("| STAT | INFO | ", 1)[1])
                self.assertEqual(summary["success"], 5000)
                self.assertGreater(summary["fail"], 0)
                self.assertEqual(summary["fail"], summary["reassignments"])
                self.assertIsNone(summary["execution_time"])  # 미연동 시간을 결과로 꾸미지 않음
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()
                for thread in threads:
                    thread.join(timeout=20)


if __name__ == "__main__":
    unittest.main()
