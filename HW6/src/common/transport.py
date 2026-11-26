"""한 소켓의 줄 헤더와 바이너리 본문이 같은 수신 버퍼를 사용함."""

from __future__ import annotations

import socket
import threading

from .contracts import ConnClosed


class Conn:
    """줄 헤더와 바이너리 본문의 수신 경계를 관리함."""

    def __init__(self, sock: socket.socket) -> None:
        """소켓별 수신 버퍼와 종료 신호를 준비함."""
        self.sock = sock
        self._rbuf = bytearray()
        self._closed = threading.Event()
        self._close_lock = threading.Lock()

    def _check_open(self) -> None:
        """닫힌 연결의 송수신을 차단함."""
        if self._closed.is_set():
            raise ConnClosed("connection closed")

    def _recv(self) -> None:
        """받은 바이트를 버퍼에 추가하고 연결 종료를 구분함."""
        self._check_open()
        try:
            data = self.sock.recv(65536)
        except OSError as exc:
            if self._closed.is_set():
                raise ConnClosed("connection closed") from exc
            raise
        if not data:
            raise ConnClosed("EOF before complete response")
        self._rbuf.extend(data)

    def read_line(self) -> str:
        """줄바꿈까지 읽고 남은 데이터는 버퍼에 보존함."""
        self._check_open()
        while True:
            self._check_open()
            end = self._rbuf.find(b"\n")
            if end >= 0:
                line = bytes(self._rbuf[:end])
                del self._rbuf[:end + 1]
                return line.decode("utf-8")
            self._recv()

    def read_exact(self, n: int) -> bytes:
        """버퍼와 소켓에서 필요한 바이트 수만큼 읽음."""
        if type(n) is not int:
            raise TypeError("n must be int")
        if n < 0:
            raise ValueError("n must be nonnegative")
        self._check_open()
        while len(self._rbuf) < n:
            self._recv()
        self._check_open()
        data = bytes(self._rbuf[:n])
        del self._rbuf[:n]
        return data

    def send_line(self, text: str) -> None:
        """한 줄을 UTF-8과 LF로 인코딩해 전송함."""
        if not isinstance(text, str):
            raise TypeError("text must be str")
        if "\n" in text or "\r" in text:
            raise ValueError("send_line takes one line without CR/LF")
        self.send_all((text + "\n").encode("utf-8"))

    def send_all(self, data: bytes) -> None:
        """헤더나 바이너리 데이터를 끝까지 전송함."""
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        self._check_open()
        try:
            self.sock.sendall(data)
        except OSError as exc:
            if self._closed.is_set():
                raise ConnClosed("connection closed") from exc
            raise

    def close(self) -> None:
        """대기 중인 통신을 깨우고 연결을 한 번만 닫음."""
        with self._close_lock:
            if self._closed.is_set():
                return
            self._closed.set()
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                self.sock.close()
