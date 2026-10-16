"""줄 단위 HW3 메시지 규약을 검사한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .settings import TASK_COUNT, WORKER_COUNT


class ProtocolError(ValueError):
    """메시지가 공통 통신 규약을 따르지 않을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class Message:
    kind: str
    fields: tuple[str, ...] = ()


Validator = Callable[[tuple[str, ...]], None]


def _integer(value: str, name: str, minimum: int, maximum: int | None = None) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise ProtocolError(f"{name} must be a decimal integer")
    number = int(value)
    if number < minimum or (maximum is not None and number > maximum):
        limit = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise ProtocolError(f"{name} must be {limit}")
    return number


def _worker(value: str, name: str = "worker") -> int:
    return _integer(value, name, 1, WORKER_COUNT)


def _task(value: str) -> int:
    return _integer(value, "task", 0, TASK_COUNT - 1)


def _epoch(value: str, minimum: int = 1) -> int:
    return _integer(value, "epoch", minimum)


def _port(value: str) -> int:
    return _integer(value, "port", 1, 65_535)


def _no_fields(fields: tuple[str, ...]) -> None:
    if fields:
        raise ProtocolError("message takes no fields")


def _one_worker(fields: tuple[str, ...]) -> None:
    _expect_count(fields, 1)
    _worker(fields[0])


def _expect_count(fields: tuple[str, ...], count: int) -> None:
    if len(fields) != count:
        raise ProtocolError(f"expected {count} fields, got {len(fields)}")


def _hello_or_ring(fields: tuple[str, ...]) -> None:
    _expect_count(fields, 3)
    _worker(fields[0])
    if not fields[1]:
        raise ProtocolError("host must not be empty")
    _port(fields[2])


def _result(fields: tuple[str, ...]) -> None:
    _expect_count(fields, 3)
    _task(fields[0])
    _epoch(fields[1])
    _integer(fields[2], "result", 0)


def _assign(fields: tuple[str, ...]) -> None:
    _expect_count(fields, 2)
    _task(fields[0])
    if _epoch(fields[1]) != 1:
        raise ProtocolError("ASSIGN epoch must be 1")


def _takeover(fields: tuple[str, ...]) -> None:
    _expect_count(fields, 3)
    _task(fields[0])
    _epoch(fields[1], 2)
    prefix = "from="
    if not fields[2].startswith(prefix):
        raise ProtocolError("TAKEOVER source must use from=<worker>")
    _worker(fields[2][len(prefix) :], "source worker")


def _ack(fields: tuple[str, ...]) -> None:
    _expect_count(fields, 1)
    _task(fields[0])


def _reject_stale(fields: tuple[str, ...]) -> None:
    _expect_count(fields, 2)
    _task(fields[0])
    if fields[1] not in {"DEAD", "DONE", "EPOCH"}:
        raise ProtocolError("invalid REJECT_STALE reason")


def _ckpt(fields: tuple[str, ...]) -> None:
    _expect_count(fields, 4)
    _task(fields[0])
    _epoch(fields[1])
    _integer(fields[2], "step", 1, 9)
    _integer(fields[3], "partial", 0)


_VALIDATORS: dict[str, Validator] = {
    "HELLO": _hello_or_ring,
    "RING_OK": _one_worker,
    "HB": _one_worker,
    "REQ": _one_worker,
    "RESULT": _result,
    "REJOIN": _one_worker,
    "RING": _hello_or_ring,
    "START": _no_fields,
    "ASSIGN": _assign,
    "NO_TASK": _no_fields,
    "TAKEOVER": _takeover,
    "ACK": _ack,
    "REJECT_STALE": _reject_stale,
    "WELCOME": _no_fields,
    "RETRY_LATER": _no_fields,
    "BYE": _no_fields,
    "PEER": _one_worker,
    "CKPT": _ckpt,
    "LAUNCHER": _no_fields,
    "CRASH": _no_fields,
    "RESTART": _no_fields,
    "READY": _one_worker,
    "REJOINED": _one_worker,
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
    validator = _VALIDATORS.get(message.kind)
    if validator is None:
        raise ProtocolError(f"unknown message kind: {message.kind}")
    validator(message.fields)


def encode(message: Message) -> str:
    """메시지를 검사하고 마지막 LF 없이 문자열로 변환한다."""

    _validate(message)
    return " ".join((message.kind, *message.fields))


def parse(line: str) -> Message:
    """LF 구분자를 제거한 메시지 한 줄을 해석한다."""

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
