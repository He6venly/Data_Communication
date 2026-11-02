import queue
import socket
import threading
import time
import unittest

from src.assigner.partition import bands
from src.assigner.server import accept_workers
from src.assigner.storage import Canvas
from src.assigner.transport import LineConnection, ProtocolError


class StartupTests(unittest.TestCase):
    def canvases(self):
        return tuple(Canvas(tuple(f"{i}:{y:02d}".ljust(160) for y in range(80)), "")
                     for i in range(3))

    def start_server(self, n, timeout=2):
        ready, result = queue.Queue(), queue.Queue()

        def run():
            try:
                result.put(accept_workers("127.0.0.1", 0, n, 2, self.canvases(), timeout, ready.put))
            except Exception as exc:
                result.put(exc)

        thread = threading.Thread(target=run)
        thread.start()
        return ready.get(timeout=2), result, thread

    def test_all_hello_before_assignment_and_wrapped_bands(self):
        address, result, thread = self.start_server(4)
        clients = []
        connections = []
        try:
            for _ in range(4):
                client = socket.create_connection(address, timeout=2)
                clients.append(client)
                client.sendall(b"HEL")
                client.sendall(b"LO\n")
            connections = result.get(timeout=3)
            if isinstance(connections, Exception):
                raise connections
            for k, (client, (y0, y1)) in enumerate(zip(clients, bands(4))):
                reader = LineConnection(client)
                deadline = time.monotonic() + 2
                self.assertEqual(reader.read_line(deadline, 100),
                                 f"ASSIGN {k} 4 {y0} {y1} 2".encode())
                rows = [reader.read_line(deadline, 160) for _ in range(3 * (y1 - y0) + 4)]
                self.assertEqual(rows[0], self.canvases()[0].rows[y0].encode())
                self.assertEqual(rows[y1 - y0], self.canvases()[1].rows[(y0 - 1) % 80].encode())
                self.assertEqual(rows[-1], self.canvases()[2].rows[y1 % 80].encode())
        finally:
            for client in clients:
                client.close()
            for connection in connections:
                connection.close()
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())

    def test_invalid_hello_closes_connection(self):
        address, result, thread = self.start_server(1)
        with socket.create_connection(address, timeout=2) as client:
            client.sendall(b"HELLO\r\n")
            self.assertIsInstance(result.get(timeout=3), ProtocolError)
            self.assertEqual(client.recv(1), b"")
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())

    def test_startup_timeout(self):
        address, result, thread = self.start_server(1, 0.15)
        with socket.create_connection(address, timeout=2):
            self.assertIsInstance(result.get(timeout=2), TimeoutError)
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_buffered_lines(self):
        left, right = socket.socketpair()
        try:
            right.sendall(b"first\nsecond\n")
            reader = LineConnection(left)
            deadline = time.monotonic() + 1
            self.assertEqual(reader.read_line(deadline, 10), b"first")
            self.assertEqual(reader.read_line(deadline, 10), b"second")
        finally:
            left.close()
            right.close()


if __name__ == "__main__":
    unittest.main()
