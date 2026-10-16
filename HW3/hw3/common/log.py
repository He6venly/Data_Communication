"""HW3 공통 텍스트·JSON 형식을 기록하는 스레드 안전 KST 로거."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Mapping


_KST = timezone(timedelta(hours=9), name="KST")
_STATUSES = {"SUCCESS", "FAIL", "INFO", "WARN"}


class NodeLogger:
    """각 노드가 소유한 파일 하나에 완전한 로그 레코드를 기록한다."""

    def __init__(self, node: str, path: str | Path, run_id: str) -> None:
        _validate_label(node, "node")
        if not run_id or "\r" in run_id or "\n" in run_id:
            raise ValueError("run_id must be a non-empty single-line string")
        self.node = node
        self.path = Path(path)
        self.run_id = run_id
        self._lock = threading.Lock()
        self._closed = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8", newline="\n")

    def write(self, event: str, status: str, fields: Mapping[str, object]) -> None:
        _validate_label(event, "event")
        if status not in _STATUSES:
            raise ValueError(f"status must be one of {sorted(_STATUSES)}")
        if not isinstance(fields, Mapping):
            raise TypeError("fields must be a mapping")
        if "run_id" in fields or "ts_unix_ms" in fields:
            raise ValueError("fields must not replace run_id or ts_unix_ms")

        now = datetime.now(_KST)
        timestamp_ms = time.time_ns() // 1_000_000
        payload: dict[str, object] = {
            "run_id": self.run_id,
            "ts_unix_ms": timestamp_ms,
        }
        payload.update(fields)
        clock = now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        record = f"[{clock}] {self.node} | {event} | {status} | {encoded}\n"

        with self._lock:
            if self._closed:
                raise ValueError("logger is closed")
            self._file.write(record)
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._file.close()
                self._closed = True

    def __enter__(self) -> "NodeLogger":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _validate_label(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or "|" in value or "\r" in value or "\n" in value:
        raise ValueError(f"{name} must be a non-empty label without '|', CR, or LF")
