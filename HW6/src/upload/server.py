"""Peer 간 BITMAP/GET TCP 서버."""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

from src.common.contracts import (
    Env,
    EventSink,
    InvalidChunkError,
    LifecycleError,
    NoChunkError,
    NoFileError,
    OfflineError,
    ShutdownError,
    StoreIOError,
    StorePort,
)
from src.common.transport import Conn
from .limiter import RateLimiter


class UploadServer:
    """연결마다 handler 하나를 두고 동일 연결의 요청을 재사용한다."""

    def __init__(
        self,
        *,
        env: Env,
        peer_id: str,
        store: StorePort,
        stopping: threading.Event,
        emit: EventSink,
    ) -> None:
        """Peer의 bind 정보와 저장소·종료 신호를 보관하되 아직 listener를 열지 않는다."""
        self.env = env
        self.peer_id = peer_id
        self.store = store
        self.stopping = stopping
        self.emit = emit
        peer = next((p for p in env.get("peers", []) if p.get("id") == peer_id), None)
        if peer is None:
            raise ValueError(f"env에 없는 peer: {peer_id}")
        self.host = str(peer["host"])
        self.port = int(peer["port"])
        self._limiter = RateLimiter(int(peer["up_kbps"]) * 1024)
        self._lock = threading.RLock()
        self._listener: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._handlers: set[threading.Thread] = set()
        self._all_handlers: set[threading.Thread] = set()
        self._connections: set[socket.socket] = set()
        self._online = False
        self._started = False
        self._stopped = False
        self._generation = 0

    def _bind_locked(self) -> None:
        """새 listener를 bind하고 현재 연결 세대의 accept 스레드를 시작한다."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.host, self.port))
            listener.listen()
            listener.settimeout(0.5)
        except OSError:
            listener.close()
            raise
        self._generation += 1
        generation = self._generation
        self._listener = listener
        self._online = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, args=(listener, generation),
            name=f"upload-accept-{self.peer_id}", daemon=True,
        )
        self._accept_thread.start()

    def start(self) -> None:
        """최초 listener를 열고 이미 실행 중이면 중복 기동을 무시한다."""
        with self._lock:
            if self._stopped:
                raise LifecycleError("종료된 UploadServer")
            if self._online:
                return
            self._started = True
            self._bind_locked()

    def _close_connections_locked(self) -> None:
        """현재 세대의 모든 소켓을 닫아 대기 중인 handler를 깨운다."""
        for sock in tuple(self._connections):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self._connections.clear()

    def offline(self) -> None:
        """crash 시 listener와 진행 중 연결을 응답 없이 닫는다."""
        with self._lock:
            if not self._online:
                return
            self._online = False
            self._generation += 1
            listener, self._listener = self._listener, None
            if listener is not None:
                try:
                    listener.close()
                except OSError:
                    pass
            self._close_connections_locked()

    def online(self) -> None:
        """일시 중단 뒤 새 세대의 listener를 다시 열어 이전 연결과 분리한다."""
        with self._lock:
            if self._stopped:
                raise LifecycleError("stop 뒤에는 다시 online할 수 없음")
            if self._online:
                return
            if not self._started:
                raise LifecycleError("start 전에는 online할 수 없음")
            self._bind_locked()

    def _accept_loop(self, listener: socket.socket, generation: int) -> None:
        """연결을 받아 연결마다 전용 handler 스레드를 배정한다."""
        while True:
            with self._lock:
                if not self._online or generation != self._generation:
                    return
            try:
                sock, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            sock.settimeout(5.0)
            with self._lock:
                if not self._online or generation != self._generation:
                    sock.close()
                    continue
                self._all_handlers = {t for t in self._all_handlers if t.is_alive()}
                self._connections.add(sock)
                thread = threading.Thread(
                    target=self._handle_connection,
                    args=(sock, generation),
                    name=f"upload-{self.peer_id}-{sock.fileno()}",
                    daemon=True,
                )
                self._handlers.add(thread)
                self._all_handlers.add(thread)
                thread.start()

    def _is_current(self, generation: int) -> bool:
        """스레드가 현재 online 세대에서 응답할 수 있는지 확인한다."""
        with self._lock:
            return self._online and generation == self._generation and not self.stopping.is_set()

    def _respond(
        self, conn: Conn, sock: socket.socket, generation: int, data: bytes, *, payload_size: int = 0
    ) -> None:
        """본문 속도를 예약한 뒤 세대가 유효할 때만 연결로 응답한다."""
        self._limiter.take(payload_size)
        if not self._is_current(generation):
            raise OfflineError("Peer가 오프라인 상태임")
        conn.send_all(data)

    def _handle_connection(self, sock: socket.socket, generation: int) -> None:
        """한 TCP 연결에서 BITMAP·GET을 반복 처리하고 잘못된 명령은 유지한다."""
        conn = Conn(sock)
        try:
            while self._is_current(generation):
                line = conn.read_line()
                fields = line.split()
                if len(fields) == 2 and fields[0] == "BITMAP":
                    name = fields[1]
                    try:
                        snap = self.store.snapshot()
                        file = next((f for f in snap.files if f.name == name), None)
                        if file is None:
                            raise NoFileError("알 수 없는 파일", file=name)
                        response = f"BITMAP {file.nchunks} {file.bitmap}\n".encode("ascii")
                    except NoFileError:
                        response = b"ERR NOFILE\n"
                    self._respond(conn, sock, generation, response)
                    continue
                if len(fields) == 3 and fields[0] == "GET":
                    name = fields[1]
                    try:
                        idx = int(fields[2])
                    except ValueError:
                        self._respond(conn, sock, generation, b"ERR BADCMD\n")
                        continue
                    try:
                        data = self.store.read_chunk(name, idx)
                    except NoFileError:
                        self._respond(conn, sock, generation, b"ERR NOFILE\n")
                        continue
                    except NoChunkError:
                        self._respond(conn, sock, generation, b"ERR NOCHUNK\n")
                        continue
                    except InvalidChunkError:
                        self._respond(conn, sock, generation, b"ERR BADCMD\n")
                        continue
                    packet = f"DATA {idx} {len(data)}\n".encode("ascii") + data
                    self._respond(conn, sock, generation, packet, payload_size=len(data))
                    self.store.record_sent(name, idx, len(data))
                    continue
                self._respond(conn, sock, generation, b"ERR BADCMD\n")
        except (OfflineError, ConnectionError, TimeoutError, OSError):
            pass
        except StoreIOError as exc:
            self.emit("ERROR", kind="local_io", operation=exc.operation, file=exc.file, message=str(exc))
            raise
        finally:
            conn.close()
            with self._lock:
                self._connections.discard(sock)
                self._handlers.discard(threading.current_thread())

    def stop(self, grace_sec: float = 3.0) -> None:
        """새 요청을 막고 업로드 유예 뒤 listener와 handler를 정해진 시간 안에 join한다."""
        if not isinstance(grace_sec, (int, float)) or grace_sec < 0 or grace_sec > 3.0:
            raise ValueError("grace_sec는 0~3초여야 함")
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            listener, self._listener = self._listener, None
            if listener is not None:
                try:
                    listener.close()
                except OSError:
                    pass
        deadline = time.monotonic() + float(grace_sec)
        while time.monotonic() < deadline:
            with self._lock:
                if not self._handlers:
                    break
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        with self._lock:
            # listener는 닫았지만 유예 중 기존 연결은 현재 세대로 응답할 수 있게 둔다.
            self._online = False
            self._generation += 1
            self._close_connections_locked()
            threads = list(self._all_handlers)
            accept = self._accept_thread
        join_deadline = time.monotonic() + 5.0
        if accept is not None and accept is not threading.current_thread():
            accept.join(max(0.0, join_deadline - time.monotonic()))
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(max(0.0, join_deadline - time.monotonic()))
        with self._lock:
            if self._handlers or (accept is not None and accept.is_alive()):
                raise ShutdownError("UploadServer 스레드가 종료되지 않음")
