"""업로드 프로토콜·속도 제한기·상태판의 기본 동작을 검사한다."""

from __future__ import annotations

import hashlib
import io
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.common.contracts import FileState, PeerView
from src.common.transport import Conn
from src.storage.store import FileStore
from src.upload.limiter import RateLimiter
from src.upload.screen import StatusScreen
from src.upload.server import UploadServer


def free_port() -> int:
    """운영체제에서 사용 가능한 임시 포트를 구한다."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class UploadTests(unittest.TestCase):
    """한 연결에서 BITMAP과 GET을 연속 처리하는 서버를 확인한다."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="hw6-upload-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = b"abcdefghijk"
        (self.root / "p1").mkdir()
        (self.root / "p1" / "sample.bin").write_bytes(self.payload)
        self.port = free_port()
        self.env = {
            "chunk_size": 8,
            "peers": [{"id": "P1", "dir": "p1", "host": "127.0.0.1", "port": self.port, "up_kbps": 10000, "down_kbps": 10000}],
            "files": [
                {"name": "sample.bin", "size": 11, "origin": "P1", "sha256": hashlib.sha256(self.payload).hexdigest()},
                {"name": "empty.bin", "size": 11, "origin": "P2", "sha256": hashlib.sha256(self.payload).hexdigest()},
            ],
        }
        self.store = FileStore(env=self.env, peer_id="P1", root=self.root, emit=lambda *_args, **_kwargs: None)
        self.store.initialize()
        self.stopping = threading.Event()
        self.server = UploadServer(env=self.env, peer_id="P1", store=self.store, stopping=self.stopping, emit=lambda *_args, **_kwargs: None)
        self.addCleanup(self.store.finalize)
        self.server.start()
        self.addCleanup(self.server.stop, 0.0)

    def test_persistent_bitmap_get_and_errors(self) -> None:
        """응답 헤더와 짧은 마지막 본문을 읽고 오류 뒤에도 연결을 재사용한다."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
        sock.settimeout(2)
        conn = Conn(sock)
        self.addCleanup(conn.close)

        conn.send_line("BITMAP sample.bin")
        self.assertEqual(conn.read_line(), "BITMAP 2 11")
        conn.send_line("GET sample.bin 1")
        header = conn.read_line().split()
        self.assertEqual(header, ["DATA", "1", "3"])
        self.assertEqual(conn.read_exact(3), b"ijk")

        conn.send_line("GET empty.bin 0")
        self.assertEqual(conn.read_line(), "ERR NOCHUNK")
        conn.send_line("BITMAP missing.bin")
        self.assertEqual(conn.read_line(), "ERR NOFILE")
        conn.send_line("GET sample.bin nope")
        self.assertEqual(conn.read_line(), "ERR BADCMD")
        self.assertEqual(self.store.snapshot().sent_bytes, 3)

    def test_stop_grace_allows_active_upload_request_to_finish(self) -> None:
        """stop은 새 연결을 닫되 유예 중 이미 처리 중인 GET 응답은 끝내게 한다."""
        limiter_entered = threading.Event()
        allow_response = threading.Event()

        class WaitingLimiter:
            def take(self, _size: int) -> None:
                limiter_entered.set()
                if not allow_response.wait(2):
                    raise TimeoutError("테스트 응답 허용 시간 초과")

        self.server._limiter = WaitingLimiter()
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
        sock.settimeout(2)
        conn = Conn(sock)
        conn.send_line("GET sample.bin 1")
        self.assertTrue(limiter_entered.wait(2))

        stop_thread = threading.Thread(target=self.server.stop, kwargs={"grace_sec": 1.0})
        stop_thread.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with self.server._lock:
                listener_closed = self.server._stopped and self.server._listener is None
            if listener_closed:
                break
            time.sleep(0.01)
        self.assertTrue(listener_closed)

        allow_response.set()
        header = conn.read_line().split()
        self.assertEqual(header, ["DATA", "1", "3"])
        self.assertEqual(conn.read_exact(3), b"ijk")
        conn.close()
        stop_thread.join(2)
        self.assertFalse(stop_thread.is_alive())

    def test_shared_limiter_and_stalled_bar(self) -> None:
        """같은 제한기 객체를 쓰고 정지 상태의 빈 구간을 x로 표시한다."""
        limiter = RateLimiter(1024)
        self.assertEqual(limiter.rate, 1024)
        self.assertEqual(StatusScreen._bar("1000", 4, stalled=True), "#xxx")

    def test_status_screen_renders_verifying_as_down(self) -> None:
        """상태 화면에 파일 진행 상태와 최근 이벤트를 표시한다."""
        file = self.store.snapshot().files[0]
        # VERIFYING 표시 규칙은 렌더 결과에서 DOWN으로 확인한다.
        from dataclasses import replace
        view = PeerView(
            peer_id="P1", elapsed_sec=1.0, online=True, policy="random", up_kbps=10000,
            down_kbps=10000, actual_up_kbps=0.0, actual_down_kbps=0.0,
            files=(replace(file, state=FileState.VERIFYING),),
        )
        stream = io.StringIO()
        screen = StatusScreen(stopping=threading.Event(), period_sec=1.0, stream=stream)
        screen.start(lambda: view, lambda _n: ("START",))
        time.sleep(0.05)
        screen.stop()
        self.assertIn("DOWN", stream.getvalue())
        self.assertIn("START", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
