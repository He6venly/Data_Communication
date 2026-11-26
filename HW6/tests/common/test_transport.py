import json
from pathlib import Path
import socket
import threading
import unittest

from src.common.contracts import ConnClosed
from src.common.transport import Conn


def socket_pair():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = None
    try:
        listener.settimeout(1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname(), timeout=1)
        server, _ = listener.accept()
        server.settimeout(1)
        return client, server
    except BaseException:
        if client is not None:
            client.close()
        raise
    finally:
        listener.close()


class ScriptedSocket:
    def __init__(self, case):
        self.chunks = [bytes.fromhex(x) for x in case["recv_chunks_hex"]]
        self.timeout = case.get("timeout_after_chunks", False)
        self.sent = bytearray()

    def recv(self, n):
        if not self.chunks:
            if self.timeout:
                raise TimeoutError("scripted timeout")
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) > n:
            self.chunks.insert(0, chunk[n:])
        return chunk[:n]

    def sendall(self, data):
        self.sent.extend(data)

    def shutdown(self, how):
        pass

    def close(self):
        pass


class TransportTests(unittest.TestCase):
    def test_shared_receive_cases(self):
        path = Path(__file__).parents[1] / "fixtures/transport.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 10)
        for case in cases:
            with self.subTest(case=case["id"]):
                conn = Conn(ScriptedSocket(case))
                self.addCleanup(conn.close)
                for op in case["operations"]:
                    call = conn.read_line if op["op"] == "read_line" else lambda: conn.read_exact(op["n"])
                    if "error" in op:
                        error = {"ConnClosed": ConnClosed, "TimeoutError": TimeoutError}[op["error"]]
                        with self.assertRaises(error):
                            call()
                    else:
                        expected = op["text"] if "text" in op else bytes.fromhex(op["hex"])
                        self.assertEqual(call(), expected)
                if "file_size" in case:
                    self.assertEqual(op["n"], min(case["chunk_size"], case["file_size"] - case["idx"] * case["chunk_size"]))

    def test_send_and_argument_errors(self):
        sock = ScriptedSocket({"recv_chunks_hex": []})
        conn = Conn(sock)
        self.addCleanup(conn.close)
        conn.send_line("한글")
        conn.send_all(b"\x00\xff\n")
        self.assertEqual(bytes(sock.sent), "한글\n".encode() + b"\x00\xff\n")
        for n in (-1, True, 1.2):
            with self.subTest(n=n), self.assertRaises((TypeError, ValueError)):
                conn.read_exact(n)
        for text in ("a\nb", "a\rb", b"bytes"):
            with self.subTest(text=text), self.assertRaises((TypeError, ValueError)):
                conn.send_line(text)

    def test_real_socket_body_and_close(self):
        left, right = socket_pair()
        conn, other = Conn(left), Conn(right)
        self.addCleanup(conn.close)
        self.addCleanup(other.close)
        left.settimeout(1)
        right.settimeout(1)
        payload = bytes(range(256)) * 512 + b"tail"
        failures = []

        def send():
            try:
                other.send_line(f"DATA 0 {len(payload)}")
                other.send_all(payload)
                other.send_line("OK")
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=send)
        thread.start()
        self.assertEqual(conn.read_line(), f"DATA 0 {len(payload)}")
        self.assertEqual(conn.read_exact(len(payload)), payload)
        self.assertEqual(conn.read_line(), "OK")
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        conn.close()
        conn.close()
        with self.assertRaises(ConnClosed):
            conn.send_line("late")

    def test_close_interrupts_blocking_read(self):
        left, right = socket_pair()
        conn = Conn(left)
        self.addCleanup(conn.close)
        self.addCleanup(right.close)
        started = threading.Event()
        result = []

        def read():
            started.set()
            try:
                conn.read_line()
            except BaseException as exc:
                result.append(exc)

        thread = threading.Thread(target=read)
        thread.start()
        self.assertTrue(started.wait(1))
        conn.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], ConnClosed)

    def test_real_timeout_and_eof(self):
        left, right = socket_pair()
        conn = Conn(left)
        self.addCleanup(conn.close)
        self.addCleanup(right.close)
        left.settimeout(0.05)
        with self.assertRaises(TimeoutError):
            conn.read_line()
        right.sendall(b"partial")
        right.close()
        with self.assertRaises(ConnClosed):
            conn.read_line()
