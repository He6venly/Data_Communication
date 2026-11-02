import socket
import threading
import time
import unittest
from unittest.mock import Mock, patch

from src.worker.transport import Connection, PhaseTimeout, ProtocolError, connect


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.sender, receiver = socket.socketpair()
        self.addCleanup(receiver.close)
        self.addCleanup(self.sender.close)
        self.connection = Connection(receiver)

    def line(self, limit=160):
        return self.connection.line(time.monotonic()+1, "recv", 1, limit)

    def test_split_and_coalesced_messages(self):
        self.sender.sendall(b"RO")
        def finish():
            self.sender.sendall(b"UND 0\n" + b" "*160 + b"\nBYE\n")
        thread = threading.Thread(target=finish)
        thread.start()
        try:
            self.assertEqual(self.line(), "ROUND 0")
            self.assertEqual(self.line(), " "*160)
            self.assertEqual(self.line(), "BYE")
        finally:
            thread.join(2)

    def test_bad_ascii_and_length(self):
        for data in (b"X\r\n", b"\xff\n", b"\t\n", b"X"*161+b"\n"):
            self.connection.buffer[:] = data
            with self.assertRaises(ProtocolError):
                self.line()

    def test_eof_mid_line(self):
        self.sender.sendall(b"ROUND")
        self.sender.close()
        with self.assertRaises(EOFError):
            self.line()

    def test_deadline_is_not_renewed_by_partial_bytes(self):
        # 데이터가 조금씩 와도 처음 정한 메시지 제한시간을 넘기면 멈추는지 확인함
        stop = threading.Event()
        def trickle():
            while not stop.wait(0.015):
                self.sender.sendall(b" ")
        thread = threading.Thread(target=trickle)
        thread.start()
        start = time.monotonic()
        try:
            with self.assertRaises(PhaseTimeout) as caught:
                self.connection.line(start+0.12, "startup", 0.12)
            self.assertEqual(caught.exception.phase, "startup")
            self.assertLess(time.monotonic()-start, 0.6)
        finally:
            stop.set()
            thread.join(2)

    def test_expired_buffered_message(self):
        self.connection.buffer[:] = b"BYE\n"
        with self.assertRaises(PhaseTimeout):
            self.connection.line(time.monotonic()-1, "recv", 1)

    def test_assignment_partitions_and_preserved_spaces(self):
        for n in (1, 4, 5, 6, 7, 8):
            for k in range(n):
                y0, y1 = 80*k//n, 80*(k+1)//n
                h = y1-y0
                self.connection.buffer[:] = (f"ASSIGN {k} {n} {y0} {y1} 11\n".encode()
                    + (b" "*159+b"X\n")*h + (b"1"*160+b"\n")*(h+2)
                    + (b"2"*160+b"\n")*(h+2) + b"ROUND 0\n")
                a = self.connection.assignment(time.monotonic()+1, 1)
                self.assertEqual((a.y0, a.y1, len(a.rows), len(a.canvas1), len(a.canvas2)),
                                 (y0, y1, h, h+2, h+2))
                self.assertEqual(a.rows[0], " "*159+"X")
                self.assertEqual(self.line(), "ROUND 0")

    def test_invalid_assignment(self):
        for header in ("ASSIGN 0 3 0 26 2", "ASSIGN 6 6 80 93 2", "ASSIGN -1 6 0 13 2",
                       "ASSIGN 0 6 0 14 2", "ASSIGN 0 1 0 80 0", "ASSIGN X 6 0 13 2", "BYE"):
            self.connection.buffer[:] = (header+"\n").encode()
            with self.assertRaises(ProtocolError):
                self.connection.assignment(time.monotonic()+1, 1)

    def test_assignment_short_picture_and_missing_rows(self):
        self.connection.buffer[:] = b"ASSIGN 0 8 0 10 2\nshort\n"
        with self.assertRaises(ProtocolError):
            self.connection.assignment(time.monotonic()+1, 1)
        self.connection.buffer[:] = b"ASSIGN 0 8 0 10 2\n" + (b" "*160+b"\n")*33
        self.sender.close()
        with self.assertRaises(EOFError):
            self.connection.assignment(time.monotonic()+1, 1)

    def test_round_order_and_halo_lengths(self):
        for data in (b"BYE\n", b"ROUND 1\n", b"ROUND 0\nshort\n"):
            self.connection.buffer[:] = data
            with self.assertRaises(ProtocolError):
                self.connection.round(0, time.monotonic()+1, "recv", 1)

    def test_send_timeout(self):
        sender = Mock()
        sender.sendall.side_effect = socket.timeout()
        with self.assertRaises(PhaseTimeout) as caught:
            Connection(sender).send(b"RESULT 0 0\n", time.monotonic()+0.08, "send", 0.08)
        self.assertEqual((caught.exception.phase, caught.exception.timeout_s), ("send", 0.08))
        sender.sendall.assert_called_once_with(b"RESULT 0 0\n")
        self.assertGreater(sender.settimeout.call_args.args[0], 0)
        self.assertLessEqual(sender.settimeout.call_args.args[0], 0.08)


class ConnectTests(unittest.TestCase):
    def test_address_retries_share_one_deadline_and_close_failed_socket(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 1))]*2
        first, second = Mock(), Mock()
        first.connect.side_effect = ConnectionRefusedError()
        with patch("src.worker.transport.socket.getaddrinfo", return_value=addresses), \
                patch("src.worker.transport.socket.socket", side_effect=[first, second]), \
                patch("src.worker.transport.time.monotonic", side_effect=[0, 0.1, 0.7, 0.8]):
            self.assertIs(connect("localhost", 1, 1), second)
        first.close.assert_called_once()
        self.assertAlmostEqual(first.settimeout.call_args.args[0], 0.9)
        self.assertAlmostEqual(second.settimeout.call_args.args[0], 0.3)
        second.close.assert_not_called()

    def test_connect_timeout_closes_socket(self):
        sock = Mock()
        sock.connect.side_effect = socket.timeout()
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 1))]
        with patch("src.worker.transport.socket.getaddrinfo", return_value=addresses), \
                patch("src.worker.transport.socket.socket", return_value=sock):
            with self.assertRaises(PhaseTimeout) as caught:
                connect("localhost", 1, 0.1)
        self.assertEqual(caught.exception.phase, "connect")
        sock.close.assert_called_once()
