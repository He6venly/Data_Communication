"""UTF-8 줄 버퍼링과 순차적인 소켓 송신을 제공한다."""

from __future__ import annotations

import codecs
from typing import Any


class LineBuffer:
    """UTF-8 바이트를 이어서 해석하고 LF로 끝난 완전한 줄을 반환한다."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        self._text = ""

    def feed(self, data: bytes) -> list[str]:
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        self._text += self._decoder.decode(data, final=False)
        pieces = self._text.split("\n")
        self._text = pieces.pop()
        return pieces


def send_line(sock: Any, line: str, send_lock: Any) -> None:
    """해당 소켓의 잠금을 획득한 상태에서 UTF-8 한 줄을 전송한다."""

    if not isinstance(line, str):
        raise TypeError("line must be a string")
    if "\r" in line or "\n" in line:
        raise ValueError("line must not contain CR or LF")
    payload = line.encode("utf-8") + b"\n"
    with send_lock:
        sock.sendall(payload)
