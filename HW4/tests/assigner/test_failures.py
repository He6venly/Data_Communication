import socket
import threading
import time
import unittest

from src.assigner.barrier import run_rounds
from src.assigner.storage import Canvas
from src.assigner.transport import LineConnection, PhaseTimeout, ProtocolError


class FailureTests(unittest.TestCase):
    def test_result_failures_and_cleanup(self):
        for case in ("wrong_k", "duplicate", "short", "non_ascii", "eof", "timeout", "edge", "save"):
            with self.subTest(case=case):
                self.check_failure(case)

    def check_failure(self, case):
        canvas = Canvas((" " * 160,) * 80, "")
        left, right = socket.socketpair()
        right.settimeout(2)
        worker_errors = []
        expected_rounds = 10 if case in ("edge", "save") else 2
        expected_error = (TimeoutError if case == "timeout" else EOFError if case == "eof"
                          else OSError if case == "save" else ProtocolError)

        def worker():
            reader = LineConnection(right)
            try:
                for r in range(expected_rounds):
                    deadline = time.monotonic() + 2
                    for _ in range(3):
                        reader.read_line(deadline, 160)
                    valid = f"RESULT {r} 0\n".encode() + (b" " * 160 + b"\n") * 2
                    if case == "wrong_k":
                        right.sendall(b"RESULT 0 1\n")
                        return
                    if case == "duplicate":
                        right.sendall(valid + valid)
                        for _ in range(3):
                            reader.read_line(time.monotonic() + 2, 160)
                        return
                    if case == "short":
                        right.sendall(b"RESULT 0 0\nshort\n" + b" " * 160 + b"\n")
                        return
                    if case == "non_ascii":
                        right.sendall(b"RESULT 0 0\n" + b"\xff" + b" " * 159 + b"\n")
                        return
                    if case == "eof":
                        right.sendall(b"RESULT 0 0\npartial")
                        return
                    if case == "timeout":
                        time.sleep(0.5)
                        return
                    if r == 9:
                        full = [b" " * 160] * 80
                        if case == "edge":
                            full[0] = b"." * 160
                        valid += b"".join(line + b"\n" for line in full)
                    right.sendall(valid)
            except (OSError, EOFError) as exc:
                if case not in ("duplicate", "edge", "save"):
                    worker_errors.append(exc)
            finally:
                right.close()

        def save(state_round, _):
            if case == "save" and state_round == 10:
                raise OSError("저장 실패")

        thread = threading.Thread(target=worker)
        thread.start()
        with self.assertRaises(expected_error) as raised:
            run_rounds([LineConnection(left)], canvas, 0.2 if case == "timeout" else 2,
                       save, lambda _: None, rounds=expected_rounds)
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(worker_errors, worker_errors)
        self.assertEqual(raised.exception.handlers_joined, 1)
        if case == "timeout":
            self.assertIsInstance(raised.exception, PhaseTimeout)
            self.assertIn(raised.exception.phase, ("recv", "barrier"))
        if case == "save":
            self.assertEqual(raised.exception.rounds_completed, 10)

    def test_partial_messages_do_not_reset_deadline(self):
        left, right = socket.socketpair()

        def drip():
            try:
                for _ in range(8):
                    right.sendall(b"a")
                    time.sleep(0.04)
            except OSError:
                pass
            finally:
                right.close()

        thread = threading.Thread(target=drip)
        thread.start()
        start = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                LineConnection(left).read_line(start + 0.15, 160)
            self.assertLess(time.monotonic() - start, 0.4)
        finally:
            left.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
