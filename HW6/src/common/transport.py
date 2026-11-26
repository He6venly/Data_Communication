"""한 소켓의 줄 헤더와 바이너리 본문이 같은 수신 버퍼를 사용함."""

from __future__ import annotations

import socket
import threading

from .contracts import ConnClosed


class Conn:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self._rbuf = bytearray()
        self._closed = threading.Event()
        self._close_lock = threading.Lock()

    def _check_open(self) -> None:
        if self._closed.is_set():
            raise ConnClosed("connection closed")

    def _recv(self) -> None:
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
        if not isinstance(text, str):
            raise TypeError("text must be str")
        if "\n" in text or "\r" in text:
            raise ValueError("send_line takes one line without CR/LF")
        self.send_all((text + "\n").encode("utf-8"))

    def send_all(self, data: bytes) -> None:
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
