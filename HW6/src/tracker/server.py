"""공통 Conn으로 TCP 요청을 받고 상태·관찰 스레드의 종료를 관리함."""

from __future__ import annotations

import socket
import threading
import time
from typing import Callable

from src.common.contracts import Env, EventSink, LifecycleError, ShutdownError
from src.common.transport import Conn
from .state import TrackerState


class TrackerServer:
    """연결당 handler와 scheduler·observer를 단일 수명으로 관리함."""

    def __init__(self, *, env: Env, emit: EventSink, port: int | None = None,
                 host: str = "0.0.0.0") -> None:
        """입력과 상태만 준비하고 start 전에는 소켓·스레드를 열지 않음."""
        self.state = TrackerState(env=env, emit=emit)
        self._port = self.state.env["tracker"]["port"] if port is None else port
        if type(self._port) is not int or not 0 <= self._port <= 65535:
            raise ValueError("port must be 0..65535")
        self._host = host
        self._guard = threading.Lock()
        self._idle = threading.Condition(self._guard)
        self._busy: set[Conn] = set()
        self._close_lock = threading.Lock()
        self._stopping = threading.Event()
        self._started = False
        self._closed = False
        self._listener: socket.socket | None = None
        self._threads: list[threading.Thread] = []
        self._handlers: dict[threading.Thread, Conn] = {}
        self._failure: Exception | None = None
        self._stop_reason = "interrupted"
        self.address: tuple[str, int] | None = None

    @property
    def failure(self) -> Exception | None:
        """보조 스레드에서 발생한 첫 실행 오류를 main에 전달함."""
        with self._guard:
            return self._failure

    def request_stop(self) -> None:
        """시그널 처리에서는 I/O 없이 종료 신호만 설정함."""
        self._stopping.set()

    def _failed(self, error: Exception) -> None:
        """스레드 오류를 보존하고 main의 종료 대기를 깨움."""
        with self._guard:
            if self._failure is None:
                self._failure = error
                self._stop_reason = "server_error"
        self._stopping.set()

    def _run(self, action: Callable, *args) -> None:
        """보조 스레드의 예외를 누락하지 않고 main으로 전달함."""
        try:
            action(*args)
        except Exception as exc:
            self._failed(exc)

    def start(self) -> None:
        """listen 성공 뒤 TCP 접수·0.5초 판정·1초 관찰을 시작함."""
        if self._started or self._closed:
            raise LifecycleError("server cannot be restarted", operation="start")
        self._started = True
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener = listener
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self._host, self._port))
            listener.listen(32)
            listener.settimeout(.25)
            self.address = listener.getsockname()
            jobs = [("accept", self._accept, (listener,)),
                    ("scheduler", self._periodic, (.5, self.state.tick)),
                    ("observer", self._periodic, (1., self.state.observe))]
            for name, action, args in jobs:
                thread = threading.Thread(target=self._run, args=(action, *args),
                                          name=f"hw6-tracker-{name}")
                self._threads.append(thread)
                thread.start()
        except BaseException:
            self.close()
            raise

    def _periodic(self, interval: float, action: Callable[[], None]) -> None:
        """종료 신호로 즉시 깨어나는 주기 작업을 실행함."""
        while not self._stopping.is_set():
            action()
            if self._stopping.wait(interval):
                return

    def _accept(self, listener: socket.socket) -> None:
        """새 연결마다 handler를 만들고 끝난 연결의 참조를 정리함."""
        while not self._stopping.is_set():
            try:
                sock, address = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._stopping.is_set():
                    return
                raise
            conn = Conn(sock)
            try:
                sock.settimeout(5)
                with self._guard:
                    if self._stopping.is_set():
                        start = False
                    else:
                        self._handlers = {t: c for t, c in self._handlers.items() if t.is_alive()}
                        thread = threading.Thread(target=self._run, args=(self._handle, conn, address[0]),
                                                  name="hw6-tracker-handler")
                        self._handlers[thread] = conn
                        thread.start()
                        start = True
                if not start:
                    conn.close()
            except BaseException:
                conn.close()
                raise

    def _handle(self, conn: Conn, src_ip: str) -> None:
        """연결 문맥을 보존하며 한 요청의 모든 응답을 Lock 밖에서 전송함."""
        peer_id = None
        try:
            while not self._stopping.is_set():
                try:
                    line = conn.read_line()
                except TimeoutError:
                    continue
                except UnicodeError:
                    line = ""
                except OSError:
                    return
                with self._idle:
                    if self._stopping.is_set():
                        return
                    self._busy.add(conn)
                try:
                    reply = self.state.handle(line, peer_id=peer_id, src_ip=src_ip)
                    peer_id = reply.peer_id
                    token = reply.delivery_token
                    try:
                        lines = reply.lines
                        if token is not None and not self.state.delivery_valid(token):
                            self.state.delivery_failed(token)
                            token = None
                            lines = ("OK",)
                        try:
                            for response in lines:
                                conn.send_line(response)
                        except OSError:
                            return
                        if token is not None:
                            self.state.delivery_succeeded(token)
                            token = None
                    finally:
                        if token is not None:
                            self.state.delivery_failed(token)
                finally:
                    with self._idle:
                        self._busy.discard(conn)
                        self._idle.notify_all()
        finally:
            conn.close()

    def wait(self) -> int:
        """정상·ABORT 조건 또는 시그널·스레드 오류까지 main에서 기다림."""
        if self.address is None or self._closed:
            raise LifecycleError("server is not running", operation="wait")
        while True:
            if self._stopping.is_set():
                with self._guard:
                    reason = self._stop_reason
                self.state.abort(reason)
                return 2
            code = self.state.exit_code()
            if code is not None:
                return code
            self._stopping.wait(.1)

    def close(self) -> None:
        """접수를 멈추고 모든 recv·send를 깨운 뒤 스레드를 제한 시간 안에 정리함."""
        with self._close_lock:
            if self._closed:
                return
            self._stopping.set()
            if self._listener is not None:
                try:
                    self._listener.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._listener.close()
                self._listener = None
            deadline = time.monotonic() + 5
            # accept를 먼저 합쳐 종료 도중 새 handler가 등록되는 경쟁을 막음.
            if self._threads and self._threads[0].ident is not None:
                self._threads[0].join(max(0., deadline - time.monotonic()))
            with self._idle:
                # 최종 BYE의 상태 반영 직후 main이 깨어나도 OK 송신은 먼저 마침.
                self._idle.wait_for(lambda: not self._busy, timeout=min(1., max(0., deadline - time.monotonic())))
                handlers = list(self._handlers.items())
            for _, conn in handlers:
                conn.close()
            threads = self._threads + [t for t, _ in handlers]
            for thread in threads:
                if thread.ident is not None:
                    thread.join(max(0., deadline - time.monotonic()))
            remaining = [t.name for t in threads if t.is_alive()]
            if remaining:
                raise ShutdownError(f"threads did not stop: {remaining}", operation="close")
            self._closed = True

