from collections import deque
import json
from threading import Lock
from time import monotonic

from src.common.contracts import LifecycleError


class EventLog:
    """JSONL 기록과 화면에 보여줄 최근 이벤트를 같이 관리함."""

    def __init__(self, *, peer_id, root, started_at):
        self.peer_id, self.started_at = peer_id, started_at
        directory = root / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / f"{peer_id}.jsonl").open("a", encoding="utf-8", newline="\n")
        self.lock = Lock()
        self.rows = deque(maxlen=64)
        self.exited = False

    def event(self, ev, **fields):
        """한 줄씩 바로 저장하고 EXIT 뒤에는 추가 기록을 막음."""
        if {"t", "peer", "ev"} & fields.keys():
            raise ValueError("reserved log field")
        with self.lock:
            if self.file.closed or self.exited:
                raise LifecycleError("log already ended", operation="log")
            row = json.dumps(dict(t=monotonic()-self.started_at, peer=self.peer_id, ev=ev, **fields),
                             ensure_ascii=False, allow_nan=False)
            self.file.write(row + "\n")
            self.file.flush()
            self.rows.append(row)
            self.exited = ev == "EXIT"

    def recent(self, n=5):
        """최근 n개 이벤트를 시간순 복사본으로 돌려줌."""
        with self.lock:
            return tuple(self.rows)[-n:] if n > 0 else ()

    def close(self):
        with self.lock:
            self.file.close()
