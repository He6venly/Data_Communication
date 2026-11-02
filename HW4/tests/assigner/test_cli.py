import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from src.assigner.transport import LineConnection


class CliTests(unittest.TestCase):
    def test_startup_timeout_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs, output = root / "canvas", root / "run"
            inputs.mkdir()
            for i in range(3):
                (inputs / f"canvas{i}.txt").write_bytes((b" " * 160 + b"\n") * 80)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            result = subprocess.run([
                sys.executable, "-m", "src.assigner", "--host", "127.0.0.1", "--port", str(port),
                "--team", "2", "--canvas-dir", str(inputs), "--out-dir", str(output),
                "--run-id", "timeout-1", "--n", "1", "--startup-timeout", "0.1",
            ], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stderr)
            lines = (output / "logs" / "Assigner.txt").read_text(encoding="utf-8").splitlines()
            final = json.loads(lines[-1].split(" | ")[-1])
            self.assertIn(" | TERMINATE | FAIL | ", lines[-1])
            self.assertEqual((final["reason"], final["phase"], final["timeout_s"]), ("timeout", "startup", 0.1))
            self.assertEqual((final["rounds_completed"], final["handlers_joined"]), (0, 0))

    def test_full_run_with_fake_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs, output = root / "canvas", root / "run"
            inputs.mkdir()
            row = b"." + b" " * 159
            data = (row + b"\n") * 80
            for i in range(3):
                (inputs / f"canvas{i}.txt").write_bytes(data)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            process = subprocess.Popen([
                sys.executable, "-m", "src.assigner", "--host", "127.0.0.1", "--port", str(port),
                "--team", "2", "--canvas-dir", str(inputs), "--out-dir", str(output),
                "--run-id", "test-1", "--n", "1", "--startup-timeout", "10", "--io-timeout", "10",
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                ready = process.stdout.readline()
                self.assertIn(" | INIT | SUCCESS | ", ready)
                with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
                    sock.sendall(b"HELLO\n")
                    reader = LineConnection(sock)
                    deadline = time.monotonic() + 10
                    self.assertEqual(reader.read_line(deadline, 80), b"ASSIGN 0 1 0 80 2")
                    for _ in range(244):
                        self.assertEqual(reader.read_line(deadline, 160), row)
                    for r in range(3000):
                        deadline = time.monotonic() + 10
                        self.assertEqual(reader.read_line(deadline, 80), f"ROUND {r}".encode())
                        self.assertEqual(reader.read_line(deadline, 160), row)
                        self.assertEqual(reader.read_line(deadline, 160), row)
                        response = f"RESULT {r} 0\n".encode() + (row + b"\n") * (82 if (r + 1) % 10 == 0 else 2)
                        sock.sendall(response)
                    self.assertEqual(reader.read_line(time.monotonic() + 10, 80), b"BYE")
                _, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
                process.stdout.close()
                process.stderr.close()
            info = json.loads((output / "run_info.json").read_text(encoding="utf-8"))
            self.assertEqual((info["n"], info["n_mode"], info["team"]), (1, "fixed", 2))
            self.assertEqual((output / "round3000.txt").read_bytes(), data)
            lines = (output / "logs" / "Assigner.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(sum(" | BARRIER | " in line for line in lines), 30)
            final = [line for line in lines if " | TERMINATE | SUCCESS | " in line]
            self.assertEqual(len(final), 1)
            fields = json.loads(final[0].split(" | ")[-1])
            self.assertEqual((fields["rounds_completed"], fields["handlers_joined"]), (3000, 1))
            self.assertEqual((fields["normal_rounds"], fields["full_rounds"]), (2700, 300))


if __name__ == "__main__":
    unittest.main()
