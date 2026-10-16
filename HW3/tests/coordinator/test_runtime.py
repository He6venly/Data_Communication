from contextlib import redirect_stdout
import io
import socket
import threading
import time
import unittest

from hw3.coordinator.__main__ import Coordinator
from hw3.coordinator.dispatcher import dispatcher_loop, STOP
from hw3.coordinator.listener import Channel
from hw3.common.protocol import parse


class Logger:
    def __init__(self):
        self.records = []
    def write(self, event, status, fields):
        self.records.append((event, status, fields))
    def close(self):
        pass


class RuntimeTests(unittest.TestCase):
    def test_console_filter_preserves_full_log_and_quiet_suppresses_only_console(self):
        logger = Logger()
        app = Coordinator("127.0.0.1", 0, logger)
        events = []
        events.append(app.tables.event("REJOIN", "SUCCESS", worker=4, rejoin_count=1, pending=700))
        for task in (300, 301):
            events.append(app.tables.event("ASSIGN", task=task, epoch=1, worker=4, rejoin_count=1))
            events.append(app.tables.event("COMMIT", "SUCCESS", task=task, epoch=1, worker=4,
                                           rejoin_count=1, commit_count=1, result=6000))
        stream = io.StringIO()
        with redirect_stdout(stream):
            app.publish(events)
        self.assertEqual(len(logger.records), len(events))
        self.assertIn("Task=300", stream.getvalue())
        self.assertIn("반영 완료", stream.getvalue())
        self.assertNotIn("Task=301", stream.getvalue())
        app.console = False
        stream = io.StringIO()
        with redirect_stdout(stream):
            app.publish(events)
        self.assertEqual(stream.getvalue(), "")
        self.assertEqual(len(logger.records), 2*len(events))

    def test_rejoin_reply_precedes_racing_req_without_state_locks_during_send(self):
        app = Coordinator("127.0.0.1", 0, Logger(), console=False)
        entered, release = threading.Event(), threading.Event()
        writes = []
        class Socket:
            def sendall(self, data):
                # Socket ordering lock is allowed; state locks during I/O are not.
                for lock in (app.tables.lock, app.tables.tasks[0].lock):
                    if not lock.acquire(blocking=False):
                        raise AssertionError("business lock held during send")
                    lock.release()
                if data == b"WELCOME\n":
                    entered.set()
                    if not release.wait(2):
                        raise TimeoutError("test did not release WELCOME")
                writes.append(data)
        channels = [Channel(Socket()) for _ in range(10)]
        for i, channel in enumerate(channels, 1):
            app.tables.hello(channel, i, "127.0.0.1", 7000+i)
        app.tables.phase = "RING"
        for i in range(1, 11):
            app.tables.ring_ok(i)
        app.tables.begin()
        app.tables.workers[4].state = "DEAD"
        threads = [threading.Thread(target=dispatcher_loop, args=(app,)) for _ in range(2)]
        try:
            app.requests.put((channels[3], parse("REJOIN 4")))
            threads[0].start()
            self.assertTrue(entered.wait(1))
            app.requests.put((channels[3], parse("REQ 4")))
            threads[1].start()
            self.assertEqual(writes, [])
        finally:
            release.set()
            for _ in threads:
                app.requests.put(STOP)
            for thread in threads:
                if thread.ident is not None:
                    thread.join(3)
        self.assertEqual(writes, [b"WELCOME\n", b"ASSIGN 0 1\n"])

    def test_real_tcp_startup_sender_identity_and_shutdown_thread_structure(self):
        logger = Logger()
        app = Coordinator("127.0.0.1", 0, logger, console=False)
        main = threading.Thread(target=app.run)
        main.start()
        sockets = []
        try:
            deadline = time.monotonic()+3
            while not any(e == "INIT" for e, _, _ in logger.records):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            address = app.server.getsockname()
            for i in range(1, 11):
                sock = socket.create_connection(address, timeout=2)
                sock.settimeout(.1)
                sockets.append(sock)
                sock.sendall(f"HELLO {i} 127.0.0.1 {7000+i}\n".encode())
            def receive(sock, kind):
                data = b""
                deadline = time.monotonic()+3
                while time.monotonic() < deadline:
                    try:
                        data += sock.recv(65536)
                    except socket.timeout:
                        continue
                    if kind.encode() in data:
                        return data
                self.fail(f"missing {kind}")
            for sock in sockets:
                receive(sock, "RING")
            for i, sock in enumerate(sockets[:9], 1):
                sock.sendall(f"RING_OK {i}\n".encode())
            self.assertFalse(app.started.wait(.1))
            sockets[9].sendall(b"RING_OK 10\n")
            self.assertTrue(app.started.wait(3))
            for sock in sockets:
                receive(sock, "START")
            self.assertEqual(len(app.threads), 8)
            sockets[0].sendall(b"REQ 2\nREQ 1\n")
            receive(sockets[0], "ASSIGN 0 1")
            self.assertTrue(any(e == "PROTOCOL" for e, _, _ in logger.records))
        finally:
            app.fail("test requested shutdown")
            main.join(5)
            for sock in sockets:
                sock.close()
        self.assertFalse(main.is_alive())
        self.assertTrue(all(not t.is_alive() for t in app.threads))


if __name__ == "__main__":
    unittest.main()
