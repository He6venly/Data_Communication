"""Tracker의 단일 JSONL 작성자. 상태 Lock 밖에서 호출함."""

from __future__ import annotations

from collections import deque
import json
import math
from pathlib import Path
import threading
import time

from src.common.contracts import JSONValue, LifecycleError


class EventLog:
    """여러 스레드의 이벤트를 JSONL 파일 하나에 기록함."""

    def __init__(self, *, peer_id: str, root: Path, started_at: float) -> None:
        """로그 파일과 동시 기록용 Lock을 준비함."""
        if not isinstance(peer_id, str) or not peer_id or "/" in peer_id or "\\" in peer_id:
            raise ValueError("invalid log id")
        if not math.isfinite(started_at):
            raise ValueError("invalid started_at")
        self._peer_id = peer_id
        self._started_at = started_at
        self._lock = threading.Lock()
        self._closed = False
        self._sealed = False
        self._recent: deque[str] = deque(maxlen=50)
        directory = root / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        self._stream = (directory / f"{peer_id}.jsonl").open("a", encoding="utf-8", newline="\n")

    def event(self, ev: str, **fields: JSONValue) -> None:
        """이벤트를 한 줄로 기록하고 EXIT 뒤 추가 기록을 차단함."""
        if not isinstance(ev, str) or not ev:
            raise ValueError("event name is required")
        if {"t", "peer", "ev"}.intersection(fields):
            raise ValueError("reserved log field")
        # JSON 직렬화 실패가 파일 일부를 쓰지 않도록 먼저 검사함.
        safe_fields = json.loads(json.dumps(fields, ensure_ascii=False, allow_nan=False))
        with self._lock:
            if self._closed or self._sealed:
                raise LifecycleError("log already ended", operation="event")
            t = round(max(0.0, time.monotonic() - self._started_at), 2)
            record = {"t": t, "peer": self._peer_id, "ev": ev, **safe_fields}
            self._stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            self._stream.flush()
            if ev not in ("RECV", "SEND"):
                detail = " ".join(f"{k}={v}" for k, v in safe_fields.items())
                self._recent.append(f"{t:7.2f}  {ev:<12} {detail}".rstrip())
            if ev == "EXIT":
                self._sealed = True

    def recent(self, n: int = 5) -> tuple[str, ...]:
        """화면용 최근 이벤트를 시간순 복사본으로 반환함."""
        if type(n) is not int:
            raise TypeError("n must be int")
        if n < 0:
            raise ValueError("n must be nonnegative")
        with self._lock:
            return tuple(self._recent)[-n:] if n else ()

    def close(self) -> None:
        """로그 파일을 한 번만 닫고 중복 종료를 허용함."""
        with self._lock:
            if not self._closed:
                self._stream.close()
                self._closed = True
