"""실제 TCP에서 송신·종료 경쟁과 보조 스레드 오류를 검사함."""

from concurrent.futures import ThreadPoolExecutor
import socket
import threading
import time
import unittest
from unittest.mock import patch

from src.common.contracts import LifecycleError
from src.common.transport import Conn
from src.tracker.server import TrackerServer
from tracker_support import env_for_tcp, exchange, until


class TrackerServerTests(unittest.TestCase):
    """전송 지점에 실패·지연을 넣어 상태와 실제 응답을 함께 확인함."""

    def setUp(self):
        """외부 네트워크 없이 임시 로컬 포트를 사용하는 서버를 준비함."""
        self.env = env_for_tcp()
        self.events = []
        self.server = self.new_server()

    def new_server(self):
        """스레드 정리가 테스트 실패 시에도 수행되도록 등록함."""
        def emit(event, **fields):
            self.events.append((event, fields))
        server = TrackerServer(env=self.env, emit=emit, host="127.0.0.1", port=0)
        self.addCleanup(server.close)
        return server

    def connect(self):
        """서버에 연결한 공통 Conn을 자동 회수 대상으로 등록함."""
        conn = Conn(socket.create_connection(self.server.address, timeout=3))
        self.addCleanup(conn.close)
        return conn

    def join(self):
        """네 개의 실제 연결로 START 조건을 충족함."""
        peers = {f"P{i}": self.connect() for i in range(1, 5)}
        for pid, conn in peers.items():
            self.assertEqual(exchange(conn, f"HELLO {pid}"), ("OK",))
        return peers

    def test_start_close_and_idle_partial_connections(self):
        """생성자는 I/O를 하지 않고 부분 수신·idle 연결도 close로 즉시 정리함."""
        self.assertIsNone(self.server.address)
        with self.assertRaises(LifecycleError):
            self.server.wait()
        self.server.start()
        address = self.server.address
        with self.assertRaises(LifecycleError):
            self.server.start()
        connections = [self.connect() for _ in range(12)]
        for conn in connections:
            conn.sock.sendall(b"HELLO ")
        self.assertEqual(exchange(self.connect(), "LIST"), ("FILES 0",))
        self.server.close()
        self.server.close()
        self.assertFalse([t for t in threading.enumerate() if t.name.startswith("hw6-tracker-")])
        for conn in connections:
            with self.assertRaises(OSError):
                conn.read_line()
        with self.assertRaises(OSError):
            socket.create_connection(address, timeout=.2)
        with self.assertRaises(LifecycleError):
            self.server.start()

    def test_last_bye_reply_finishes_before_connections_close(self):
        """마지막 BYE의 상태 반영과 OK 송신 사이에 close가 겹쳐도 응답을 보존함."""
        self.server.start()
        peers = self.join()
        for pid, conn in peers.items():
            exchange(conn, f"DONE {pid} FULL")
        for pid in ("P1", "P2", "P3"):
            exchange(peers[pid], f"BYE {pid}")
        sending, release = threading.Event(), threading.Event()
        original = Conn.send_line
        def delayed(conn, text):
            self.server.state.snapshot()
            sending.set()
            if not release.wait(2):
                raise AssertionError("send not released")
            original(conn, text)
        with patch.object(Conn, "send_line", delayed), ThreadPoolExecutor(max_workers=2) as pool:
            # 요청 송신까지 patch하면 막히므로 클라이언트는 원래 송신 함수를 사용함.
            original(peers["P4"], "BYE P4")
            self.assertTrue(sending.wait(2))
            self.assertEqual(self.server.wait(), 0)
            closed = pool.submit(self.server.close)
            time.sleep(.05)
            self.assertFalse(closed.done())
            release.set()
            self.assertEqual(peers["P4"].read_line(), "OK")
            closed.result(timeout=3)
        self.assertFalse([t for t in threading.enumerate() if t.name.startswith("hw6-tracker-")])

    def test_failed_command_send_and_cancelled_delivery_retry(self):
        """실제 송신 실패·직전 취소 뒤에도 지시를 잃지 않고 한 번만 확정함."""
        self.env["crashes"] = [dict(peer="P2", at_sec=0, duration_sec=.125)]
        self.server = self.new_server()
        self.server.start()
        peers = self.join()
        self.server.state.tick()
        original = Conn.send_line
        def fail_command(conn, text):
            if text.startswith("CMD"):
                raise OSError("send failed")
            original(conn, text)
        with patch.object(Conn, "send_line", fail_command):
            with self.assertRaises(OSError):
                exchange(peers["P2"], "HEARTBEAT P2 0")
        self.assertIsNone(self.server.failure)
        self.assertEqual(self.server.state.snapshot()["crashes_sent"], [])
        conn = self.connect()
        exchange(conn, "HELLO P2")
        with patch.object(self.server.state, "delivery_valid", return_value=False):
            self.assertEqual(exchange(conn, "HEARTBEAT P2 0"), ("OK",))
        self.assertEqual(exchange(conn, "HEARTBEAT P2 0"), ("CMD DISCONNECT 0.125",))
        until(lambda: self.server.state.snapshot()["crashes_sent"])
        self.assertEqual(len(self.server.state.snapshot()["crashes_sent"]), 1)
        self.assertEqual(exchange(conn, "HEARTBEAT P2 0"), ("OK",))

    def test_handler_failure_reaches_main(self):
        """요청 처리 오류를 연결 끊김으로 숨기지 않고 서버 중단으로 전달함."""
        self.server.start()
        with patch.object(self.server.state, "handle", side_effect=RuntimeError("handler failed")):
            with self.assertRaises(OSError):
                exchange(self.connect(), "HELLO P1")
            self.assertEqual(self.server.wait(), 2)
        self.assertIsInstance(self.server.failure, RuntimeError)
        self.server.close()
        self.assertEqual(self.server.state.prepare_report(force=True)["abort"], "server_error")

    def test_periodic_failure_reaches_main(self):
        """scheduler·observer 예외도 main을 깨우고 잔여 스레드 없이 정리함."""
        for method in ("tick", "observe"):
            with self.subTest(method=method):
                server = self.new_server()
                with patch.object(server.state, method, side_effect=RuntimeError(method)):
                    server.start()
                    self.assertEqual(server.wait(), 2)
                self.assertIsInstance(server.failure, RuntimeError)
                server.close()
                self.assertFalse([t for t in threading.enumerate() if t.name.startswith("hw6-tracker-")])

