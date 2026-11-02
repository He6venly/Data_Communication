import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from src.assigner.transport import LineConnection


class DistributedTests(unittest.TestCase):
    def test_full_tcp_runs_with_uneven_bands(self):
        for n in (4, 5, 6, 7, 8):
            with self.subTest(n=n):
                self.check_run(n)

    def check_run(self, n):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "입력 자료"
            output = root / "실행 결과"
            inputs.mkdir()
            rows = [f"row{y}".encode("ascii").ljust(160, b".") for y in range(80)]
            data = b"".join(row + b"\n" for row in rows)
            for i in range(3):
                (inputs / f"canvas{i}.txt").write_bytes(data)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            process = subprocess.Popen([
                sys.executable, "-m", "src.assigner", "--host", "127.0.0.1", "--port", str(port),
                "--team", "2", "--canvas-dir", str(inputs), "--out-dir", str(output),
                "--run-id", f"fake-{n}", "--n", str(n), "--startup-timeout", "15", "--io-timeout", "15",
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            peers = []
            threads = []
            errors = []

            def worker(k, peer):
                try:
                    peer.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    reader = LineConnection(peer)
                    y0, y1 = 80 * k // n, 80 * (k + 1) // n
                    deadline = time.monotonic() + 15
                    self.assertEqual(reader.read_line(deadline, 80),
                                     f"ASSIGN {k} {n} {y0} {y1} 2".encode())
                    assigned = [reader.read_line(deadline, 160) for _ in range(3 * (y1 - y0) + 4)]
                    self.assertEqual(assigned[:y1-y0], rows[y0:y1])
                    self.assertEqual(assigned[y1-y0], rows[(y0-1) % 80])
                    self.assertEqual(assigned[-1], rows[y1 % 80])
                    for r in range(3000):
                        deadline = time.monotonic() + 15
                        self.assertEqual(reader.read_line(deadline, 80), f"ROUND {r}".encode())
                        self.assertEqual(reader.read_line(deadline, 160), rows[(y0-1) % 80])
                        self.assertEqual(reader.read_line(deadline, 160), rows[y1 % 80])
                        result_rows = [rows[y0], rows[y1-1]]
                        if (r + 1) % 10 == 0:
                            result_rows += rows[y0:y1]
                        peer.sendall(f"RESULT {r} {k}\n".encode() + b"".join(row + b"\n" for row in result_rows))
                    self.assertEqual(reader.read_line(time.monotonic() + 15, 80), b"BYE")
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    peer.close()

            try:
                ready = process.stdout.readline()
                self.assertIn(" | INIT | SUCCESS | ", ready)
                init = json.loads(ready.split(" | ")[-1])
                self.assertEqual(init["bands"], [80 * k // n for k in range(n + 1)])
                for _ in range(n):
                    peer = socket.create_connection(("127.0.0.1", port), timeout=15)
                    peer.sendall(b"HELLO\n")
                    peers.append(peer)
                threads = [threading.Thread(target=worker, args=(k, peer)) for k, peer in enumerate(peers)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=90)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
                self.assertFalse(errors, errors)
                _, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                for peer in peers:
                    peer.close()
                for thread in threads:
                    thread.join(timeout=5)
                process.communicate()
            hash8 = hashlib.sha256(data).hexdigest()[:8]
            hashes = (output / "RoundHash.txt").read_text(encoding="ascii").splitlines()
            self.assertEqual(hashes, [f"round{r:04d}.txt {hash8}" for r in range(0, 3001, 100)])
            self.assertEqual(len(list((output / "frames").glob("frame*.txt"))), 301)
            self.assertEqual((output / "frames" / "frame3000.txt").read_bytes(), data)
            log = (output / "logs" / "Assigner.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(sum(" | BARRIER | " in line for line in log), 30)
            self.assertEqual(sum(" | RESULT | " in line for line in log), 30 * n)
            final = json.loads(log[-1].split(" | ")[-1])
            self.assertIn(" | TERMINATE | SUCCESS | ", log[-1])
            self.assertEqual((final["rounds_completed"], final["handlers_joined"]), (3000, n))
            self.assertEqual(sum(final["slowest_counts"].values()), 3000)


if __name__ == "__main__":
    unittest.main()
