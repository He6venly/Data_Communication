# 줄 단위 수신과 동시 송신을 테스트한다.

import socket
import threading
import unittest

from hw3.common.transport import LineBuffer, send_line


class RecordingSocket:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def sendall(self, payload: bytes) -> None:
        self.payloads.append(payload)


class SlowSocket:
    def __init__(self) -> None:
        self.data = bytearray()

    def sendall(self, payload: bytes) -> None:
        for byte in payload:
            self.data.append(byte)


class TransportTests(unittest.TestCase):
    def test_fragmented_and_multiple_lines(self) -> None:
        buffer = LineBuffer()
        self.assertEqual([], buffer.feed(b"READY"))
        self.assertEqual(["READY 1", "REJOINED 1"], buffer.feed(b" 1\nREJOINED 1\nPART"))
        self.assertEqual(["PARTIAL"], buffer.feed(b"IAL\n"))

    def test_utf8_character_boundary(self) -> None:
        encoded = "메시지\n".encode("utf-8")
        buffer = LineBuffer()
        self.assertEqual([], buffer.feed(encoded[:2]))
        self.assertEqual(["메시지"], buffer.feed(encoded[2:]))

    def test_invalid_utf8_is_not_ignored(self) -> None:
        with self.assertRaises(UnicodeDecodeError):
            LineBuffer().feed(b"\xff\n")

    def test_send_line_adds_exactly_one_lf(self) -> None:
        target = RecordingSocket()
        send_line(target, "READY 1", threading.Lock())
        self.assertEqual([b"READY 1\n"], target.payloads)
        with self.assertRaises(ValueError):
            send_line(target, "READY 1\n", threading.Lock())
        with self.assertRaises(ValueError):
            send_line(target, "READY 1\r", threading.Lock())

    def test_concurrent_sends_do_not_interleave(self) -> None:
        target = SlowSocket()
        lock = threading.Lock()
        threads = [
            threading.Thread(target=send_line, args=(target, f"READY {i}", lock))
            for i in range(1, 11)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        lines = bytes(target.data).decode("utf-8").splitlines()
        self.assertCountEqual(lines, [f"READY {i}" for i in range(1, 11)])

    def test_socket_pair_smoke(self) -> None:
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        send_line(left, "LAUNCHER", threading.Lock())
        self.assertEqual(b"LAUNCHER\n", right.recv(100))


if __name__ == "__main__":
    unittest.main()
