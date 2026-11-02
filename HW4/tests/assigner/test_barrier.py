import socket
import select
import threading
import time
import unittest

from src.assigner.barrier import run_rounds
from src.assigner.partition import bands
from src.assigner.storage import Canvas
from src.assigner.transport import LineConnection, ProtocolError


def row(k, r, edge):
    return f"{k}:{r}:{edge}".ljust(160)


class BarrierTests(unittest.TestCase):
    def test_workers_and_snapshot(self):
        for n in (4, 6, 7):
            with self.subTest(n=n):
                self.check_workers_and_snapshot(n)

    def check_workers_and_snapshot(self, n):
        canvas = Canvas(tuple(f"initial:{y}".ljust(160) for y in range(80)), "")
        pairs = [socket.socketpair() for _ in range(n)]
        connections = [LineConnection(pair[0]) for pair in pairs]
        errors = []

        def worker(k, sock):
            reader = LineConnection(sock)
            try:
                for r in range(10):
                    deadline = time.monotonic() + 5
                    self.assertEqual(reader.read_line(deadline, 80), f"ROUND {r}".encode())
                    top = reader.read_line(deadline, 160).decode()
                    bottom = reader.read_line(deadline, 160).decode()
                    y0, y1 = bands(n)[k]
                    if r == 0:
                        self.assertEqual((top, bottom), (canvas.rows[(y0 - 1) % 80], canvas.rows[y1 % 80]))
                    else:
                        self.assertEqual((top, bottom), (row((k - 1) % n, r - 1, "last"),
                                                         row((k + 1) % n, r - 1, "first")))
                    first, last = row(k, r, "first"), row(k, r, "last")
                    lines = [f"RESULT {r} {k}", first, last]
                    if r == 9:
                        lines += [first] + [row(k, r, "middle")] * (y1 - y0 - 2) + [last]
                    sock.sendall(("\n".join(lines) + "\n").encode())
                self.assertEqual(reader.read_line(time.monotonic() + 5, 80), b"BYE")
            except BaseException as exc:
                errors.append(exc)
            finally:
                sock.close()

        threads = [threading.Thread(target=worker, args=(k, pair[1])) for k, pair in enumerate(pairs)]
        for thread in threads:
            thread.start()
        snapshots, measurements = [], []
        try:
            run_rounds(connections, canvas, 5, lambda r, frame: snapshots.append((r, frame)),
                       measurements.append, rounds=10)
        finally:
            for thread in threads:
                thread.join(timeout=5)
        self.assertFalse(errors, errors)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([r for r, _ in snapshots], [0, 10])
        self.assertEqual(snapshots[1][1][0], row(0, 9, "first"))
        self.assertEqual(snapshots[1][1][-1], row(n - 1, 9, "last"))
        self.assertEqual(len(measurements), 10)
        self.assertEqual(sum(m.full for m in measurements), 1)
        self.assertTrue(all(m.bytes_sent_received > 0 for m in measurements))

    def test_invalid_result_releases_workers(self):
        canvas = Canvas((" " * 160,) * 80, "")
        left, right = socket.socketpair()

        def worker():
            reader = LineConnection(right)
            deadline = time.monotonic() + 2
            for _ in range(3):
                reader.read_line(deadline, 160)
            right.sendall(b"RESULT 1 0\n")
            right.close()

        thread = threading.Thread(target=worker)
        thread.start()
        with self.assertRaises(ProtocolError) as raised:
            run_rounds([LineConnection(left)], canvas, 2, lambda *_: None, lambda _: None, rounds=1)
        self.assertEqual((raised.exception.k, raised.exception.round, raised.exception.handlers_joined), (0, 0, 1))
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_initial_save_failure_closes_connection(self):
        canvas = Canvas((" " * 160,) * 80, "")
        left, right = socket.socketpair()
        try:
            def fail_save(*_):
                raise OSError("저장 실패")

            with self.assertRaises(OSError) as raised:
                run_rounds([LineConnection(left)], canvas, 2, fail_save, lambda _: None)
            self.assertEqual((raised.exception.rounds_completed, raised.exception.handlers_joined), (0, 0))
            self.assertEqual(right.recv(1), b"")
        finally:
            right.close()

    def test_barrier_waits_for_last_worker(self):
        canvas = Canvas((" " * 160,) * 80, "")
        pairs = [socket.socketpair() for _ in range(4)]
        errors = []

        def coordinator():
            try:
                run_rounds([LineConnection(pair[0]) for pair in pairs], canvas, 3,
                           lambda *_: None, lambda _: None, rounds=2)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=coordinator)
        readers = [LineConnection(pair[1]) for pair in pairs]
        thread.start()
        try:
            for reader in readers:
                deadline = time.monotonic() + 3
                self.assertEqual(reader.read_line(deadline, 80), b"ROUND 0")
                reader.read_line(deadline, 160)
                reader.read_line(deadline, 160)
            for k in range(1, 4):
                pairs[k][1].sendall(f"RESULT 0 {k}\n".encode() + (b" " * 160 + b"\n") * 2)
            self.assertFalse(select.select([pair[1] for pair in pairs], [], [], 0.1)[0])
            pairs[0][1].sendall(b"RESULT 0 0\n" + (b" " * 160 + b"\n") * 2)
            for k, reader in enumerate(readers):
                deadline = time.monotonic() + 3
                self.assertEqual(reader.read_line(deadline, 80), b"ROUND 1")
                reader.read_line(deadline, 160)
                reader.read_line(deadline, 160)
                pairs[k][1].sendall(f"RESULT 1 {k}\n".encode() + (b" " * 160 + b"\n") * 2)
            for reader in readers:
                self.assertEqual(reader.read_line(time.monotonic() + 3, 80), b"BYE")
        finally:
            for _, peer in pairs:
                peer.close()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors, errors)


if __name__ == "__main__":
    unittest.main()
