import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from src.worker.rules import rule3_cell, to_cyclic

ROOT = Path(__file__).resolve().parents[2]
BLANK = " "*160


def assignment(k=0, n=8):
    y0, y1 = 80*k//n, 80*(k+1)//n
    return (f"ASSIGN {k} {n} {y0} {y1} 11\n" + (BLANK+"\n")*(3*(y1-y0)+4)).encode()


class ClientTests(unittest.TestCase):
    def exchange(self, action, startup=2, io=2, prepare=None):
        # 테스트용 Assigner에 실제 Worker를 붙여서 통신이랑 로그, 종료까지 확인함
        with tempfile.TemporaryDirectory(prefix="hw4 worker ") as directory:
            logdir = Path(directory) / "logs"
            if prepare:
                prepare(logdir)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                listener.settimeout(10)
                process = subprocess.Popen([sys.executable, "-m", "src.worker", "--host", "127.0.0.1",
                    "--port", str(listener.getsockname()[1]), "--log-dir", str(logdir),
                    "--run-id", "worker-test", "--startup-timeout", str(startup), "--io-timeout", str(io)],
                    cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    with listener.accept()[0] as sock:
                        sock.settimeout(15)
                        with sock.makefile("rb") as reader:
                            self.assertEqual(reader.readline(), b"HELLO\n")
                            action(sock, reader)
                    stdout, stderr = process.communicate(timeout=15)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                    if process.stdout:
                        process.stdout.close()
                    if process.stderr:
                        process.stderr.close()
            logs = {p.name: p.read_bytes() for p in logdir.glob("*.txt")} if logdir.exists() else {}
            return process.returncode, stderr.decode("utf-8", errors="replace"), logs

    def test_3000_rounds_results_transitions_bye_and_logs(self):
        k, n = 6, 7
        y0, y1 = 80*k//n, 80*(k+1)//n
        def server(sock, reader):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            data = assignment(k, n)
            for part in (data[:2], data[2:19], data[19:]):
                sock.sendall(part)
            cyclic = [[" "]*160 for _ in range(80)]
            for r in range(3000):
                if r == 2000:
                    to_cyclic(cyclic, 0, 11)
                top, bottom = (cyclic[(y0-1) % 80], cyclic[y1 % 80]) if r >= 2000 else (BLANK, BLANK)
                sock.sendall((f"ROUND {r}\n" + "".join(top)+"\n" + "".join(bottom)+"\n").encode())
                if r >= 2000:
                    work = [cyclic[-1]] + cyclic + [cyclic[0]]
                    cyclic = [[rule3_cell(work, i, x) for x in range(160)] for i in range(1, 81)]
                    expected = ["".join(row) for row in cyclic[y0:y1]]
                else:
                    expected = [BLANK]*(y1-y0)
                self.assertEqual(reader.readline(), f"RESULT {r} {k}\n".encode())
                self.assertEqual(reader.readline(), (expected[0]+"\n").encode())
                self.assertEqual(reader.readline(), (expected[-1]+"\n").encode())
                if (r+1) % 10 == 0:
                    for row in expected:
                        self.assertEqual(reader.readline(), (row+"\n").encode())
            sock.sendall(b"BYE\n")
            self.assertEqual(reader.read(), b"")
        code, stderr, logs = self.exchange(server, startup=10, io=10)
        self.assertEqual((code, stderr), (0, ""))
        data = logs["Worker6.txt"]
        self.assertNotIn(b"\r", data)
        records = []
        for line in data.decode("utf-8").splitlines():
            stamp, event, status, body = line.split(" | ")
            self.assertTrue(stamp.endswith("WORKER6"))
            records.append((event, status, json.loads(body)))
        self.assertEqual([r[0] for r in records[:3]], ["INIT", "CONNECT", "ASSIGN"])
        self.assertTrue(all(r[2]["run_id"] == "worker-test" for r in records))
        summaries = [r[2] for r in records if r[0] == "ROUND"]
        self.assertEqual(len(summaries), 30)
        self.assertEqual([(r["r_start"], r["r_end"], r["count"]) for r in summaries],
                         [(r, r+99, 100) for r in range(0, 3000, 100)])
        self.assertEqual([r[2]["round"] for r in records if r[0] == "REPAINT"], [1000, 2000])
        self.assertEqual(records[-1][0:2], ("TERMINATE", "SUCCESS"))
        self.assertEqual(records[-1][2]["rounds_completed"], 3000)

    def test_startup_timeout_spans_assignment_and_first_round(self):
        def server(sock, reader):
            time.sleep(0.12)
            sock.sendall(assignment())
            time.sleep(0.16)
        code, stderr, logs = self.exchange(server, startup=0.22)
        self.assertEqual(code, 1)
        self.assertIn("startup", stderr)
        self.assertIn(b'"reason": "timeout"', logs["Worker0.txt"])

    def test_timeout_before_assignment_uses_stderr(self):
        code, stderr, logs = self.exchange(lambda s, r: time.sleep(0.2), startup=0.08)
        self.assertEqual(code, 1)
        self.assertIn("startup", stderr)
        self.assertEqual(logs, {})

    def test_recv_timeout_after_first_result(self):
        def server(sock, reader):
            sock.sendall(assignment() + ("ROUND 0\n"+(BLANK+"\n")*2).encode())
            for _ in range(3):
                self.assertTrue(reader.readline())
            time.sleep(0.2)
        code, stderr, logs = self.exchange(server, io=0.08)
        self.assertEqual(code, 1)
        self.assertIn("recv", stderr)
        self.assertIn(b'"rounds_completed": 1', logs["Worker0.txt"])

    def test_early_bye_wrong_round_and_eof_fail(self):
        for payload in (b"BYE\n", b"ROUND 1\n", b"ROUND 0\nshort\n", b""):
            with self.subTest(payload=payload):
                def server(sock, reader):
                    sock.sendall(assignment() + payload)
                    sock.shutdown(socket.SHUT_WR)
                code, stderr, logs = self.exchange(server)
                self.assertEqual(code, 1)
                self.assertIn(b"TERMINATE | FAIL", logs["Worker0.txt"])
                self.assertNotIn(b"TERMINATE | SUCCESS", logs["Worker0.txt"])

    def test_existing_log_is_preserved(self):
        def prepare(path):
            path.mkdir()
            (path / "Worker0.txt").write_bytes(b"previous run\n")
        code, stderr, logs = self.exchange(lambda s, r: s.sendall(assignment()), prepare=prepare)
        self.assertEqual(code, 1)
        self.assertEqual(logs["Worker0.txt"], b"previous run\n")

    def test_cli_invalid_values(self):
        base = ["--host", "127.0.0.1", "--port", "9000", "--log-dir", "unused", "--run-id", "test"]
        for option, value in (("--port", "0"), ("--port", "65536"), ("--connect-timeout", "nan"),
                              ("--startup-timeout", "inf"), ("--io-timeout", "-1"), ("--run-id", "")):
            result = subprocess.run([sys.executable, "-m", "src.worker", *base, option, value],
                                    cwd=ROOT, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)
