"""UTF-8 line buffering and serialized socket writes."""

from __future__ import annotations

import codecs
from typing import Any


class LineBuffer:
    """Incrementally decode UTF-8 bytes and return complete LF-delimited lines."""

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
    """Send one UTF-8 line while holding the lock dedicated to *sock*."""

    if not isinstance(line, str):
        raise TypeError("line must be a string")
    if "\r" in line or "\n" in line:
        raise ValueError("line must not contain CR or LF")
    payload = line.encode("utf-8") + b"\n"
    with send_lock:
        sock.sendall(payload)
