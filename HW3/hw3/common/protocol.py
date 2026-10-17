# 메시지 형식과 입력값을 검사한다.

from __future__ import annotations

from dataclasses import dataclass

from .settings import TASK_COUNT, WORKER_COUNT


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Message:
    kind: str
    fields: tuple[str, ...] = ()


def _integer(value: str, name: str, minimum: int, maximum: int | None = None) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise ProtocolError(f"{name} must be a decimal integer")
    number = int(value)
    if number < minimum or (maximum is not None and number > maximum):
        limit = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise ProtocolError(f"{name} must be {limit}")
    return number


_FIELD_COUNTS = {
    "HELLO": 3,
    "RING_OK": 1,
    "HB": 1,
    "REQ": 1,
    "RESULT": 3,
    "REJOIN": 1,
    "RING": 3,
    "START": 0,
    "ASSIGN": 2,
    "NO_TASK": 0,
    "TAKEOVER": 3,
    "ACK": 1,
    "REJECT_STALE": 2,
    "WELCOME": 0,
    "RETRY_LATER": 0,
    "BYE": 0,
    "PEER": 1,
    "CKPT": 4,
    "LAUNCHER": 0,
    "CRASH": 0,
    "RESTART": 0,
    "READY": 1,
    "REJOINED": 1,
}


def _validate(message: Message) -> None:
    if not isinstance(message.kind, str) or not isinstance(message.fields, tuple):
        raise ProtocolError("Message requires a string kind and tuple fields")
    if any(not isinstance(field, str) for field in message.fields):
        raise ProtocolError("all message fields must be strings")
    if any("\r" in token or "\n" in token for token in (message.kind, *message.fields)):
        raise ProtocolError("CR/LF is not allowed inside a message")
    if any(not token or any(char.isspace() for char in token) for token in (message.kind, *message.fields)):
        raise ProtocolError("message tokens must be non-empty and contain no whitespace")
    kind, fields = message.kind, message.fields
    count = _FIELD_COUNTS.get(kind)
    if count is None:
        raise ProtocolError(f"unknown message kind: {message.kind}")
    if len(fields) != count:
        raise ProtocolError(f"expected {count} fields, got {len(fields)}")

    if kind in {"HELLO", "RING", "RING_OK", "HB", "REQ", "REJOIN", "PEER", "READY", "REJOINED"}:
        _integer(fields[0], "worker", 1, WORKER_COUNT)
        if kind in {"HELLO", "RING"}:
            _integer(fields[2], "port", 1, 65_535)
    elif kind in {"RESULT", "ASSIGN", "TAKEOVER", "CKPT"}:
        _integer(fields[0], "task", 0, TASK_COUNT - 1)
        _integer(fields[1], "epoch", 2 if kind == "TAKEOVER" else 1)
        if kind == "RESULT":
            _integer(fields[2], "result", 0)
        elif kind == "ASSIGN":
            if int(fields[1]) != 1:
                raise ProtocolError("ASSIGN epoch must be 1")
        elif kind == "TAKEOVER":
            if not fields[2].startswith("from="):
                raise ProtocolError("TAKEOVER source must use from=<worker>")
            _integer(fields[2][5:], "source worker", 1, WORKER_COUNT)
        elif kind == "CKPT":
            _integer(fields[2], "step", 1, 9)
            _integer(fields[3], "partial", 0)
    elif kind in {"ACK", "REJECT_STALE"}:
        _integer(fields[0], "task", 0, TASK_COUNT - 1)
        if kind == "REJECT_STALE" and fields[1] not in {"DEAD", "DONE", "EPOCH"}:
            raise ProtocolError("invalid REJECT_STALE reason")


def encode(message: Message) -> str:

    _validate(message)
    return " ".join((message.kind, *message.fields))


def parse(line: str) -> Message:

    if not isinstance(line, str):
        raise ProtocolError("line must be a string")
    if not line or "\r" in line or "\n" in line:
        raise ProtocolError("message must be one non-empty LF-free line")
    if line.strip() != line or "\t" in line or "  " in line:
        raise ProtocolError("message fields must be separated by one space")
    parts = line.split(" ")
    message = Message(parts[0], tuple(parts[1:]))
    _validate(message)
    return message
