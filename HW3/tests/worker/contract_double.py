"""TEST ONLY: the published common API until its owner supplies real modules.

Installed explicitly by tests, never imported/fallback-selected by product code.
This does not constitute a common implementation or integration verification.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import threading
import time
from types import ModuleType


@dataclass(frozen=True)
class Message:
    kind: str
    fields: tuple[str, ...]


class ProtocolError(ValueError):
    pass


def parse(line):
    parts = line.split()
    if not parts:
        raise ProtocolError("empty line")
    kind, fields = parts[0], tuple(parts[1:])
    sizes = {"HELLO": 3, "RING_OK": 1, "HB": 1, "REQ": 1, "RESULT": 3,
             "REJOIN": 1, "RING": 3, "START": 0, "ASSIGN": 2, "NO_TASK": 0,
             "TAKEOVER": 3, "ACK": 1, "REJECT_STALE": 2, "WELCOME": 0,
             "RETRY_LATER": 0, "BYE": 0, "PEER": 1, "CKPT": 4,
             "LAUNCHER": 0, "CRASH": 0, "RESTART": 0, "READY": 1, "REJOINED": 1}
    if kind not in sizes or len(fields) != sizes[kind]:
        raise ProtocolError("unknown kind or wrong field count")
    try:
        if kind in {"HELLO", "RING_OK", "HB", "REQ", "REJOIN", "RING", "PEER", "READY", "REJOINED"}:
            if not 1 <= int(fields[0]) <= 10:
                raise ValueError
        if kind in {"HELLO", "RING"} and not 1 <= int(fields[2]) <= 65535:
            raise ValueError
        if kind in {"RESULT", "ASSIGN", "TAKEOVER", "CKPT", "ACK", "REJECT_STALE"}:
            if not 0 <= int(fields[0]) <= 999:
                raise ValueError
        if kind in {"RESULT", "ASSIGN", "TAKEOVER", "CKPT"} and int(fields[1]) < 1:
            raise ValueError
        if kind == "ASSIGN" and fields[1] != "1":
            raise ValueError
        if kind == "TAKEOVER" and (not fields[2].startswith("from=") or not 1 <= int(fields[2][5:]) <= 10):
            raise ValueError
        if kind == "CKPT" and (not 1 <= int(fields[2]) <= 9 or int(fields[3]) < 0):
            raise ValueError
        if kind == "RESULT" and int(fields[2]) < 0:
            raise ValueError
        if kind == "REJECT_STALE" and fields[1] not in {"DEAD", "DONE", "EPOCH"}:
            raise ValueError
    except ValueError as error:
        raise ProtocolError("invalid field") from error
    return Message(kind, fields)


def encode(message):
    line = " ".join((message.kind, *message.fields))
    parse(line)
    return line


class LineBuffer:
    def __init__(self):
        self.buffer = b""

    def feed(self, data):
        self.buffer += data
        lines = self.buffer.split(b"\n")
        self.buffer = lines.pop()
        return [line.decode("utf-8") for line in lines]


def send_line(sock, line, send_lock):
    with send_lock:
        sock.sendall((line + "\n").encode("utf-8"))


class NodeLogger:
    def __init__(self, node, path, run_id):
        self.node, self.run_id = node, run_id
        self.lock = threading.Lock()
        self.file = Path(path).open("w", encoding="utf-8")

    def write(self, event, status, fields):
        now = datetime.now(timezone(timedelta(hours=9)))
        record = {"run_id": self.run_id, "ts_unix_ms": int(time.time() * 1000), **fields}
        with self.lock:
            self.file.write(f"[{now.strftime('%H:%M:%S.%f')[:-3]}] {self.node} | {event} | {status} | "
                            + json.dumps(record, ensure_ascii=False) + "\n")
            self.file.flush()

    def close(self):
        self.file.close()


def install():
    import hw3
    common = ModuleType("hw3.common")
    common.__path__ = []
    sys.modules[common.__name__] = common
    hw3.common = common
    for name, exports in {
        "protocol": {"Message": Message, "ProtocolError": ProtocolError, "encode": encode, "parse": parse},
        "transport": {"LineBuffer": LineBuffer, "send_line": send_line},
        "log": {"NodeLogger": NodeLogger},
        "settings": {"CONTRACT_VERSION": 1},
    }.items():
        module = ModuleType(f"hw3.common.{name}")
        module.__dict__.update(exports)
        sys.modules[module.__name__] = module
        setattr(common, name, module)
