"""실행 로그를 한국 표준시와 JSON 형식으로 기록한다."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading

KST = timezone(timedelta(hours=9))


class AssignerLog:
    def __init__(self, path: Path, run_id: str):
        self.file = path.open("x", encoding="utf-8", newline="\n")
        self.run_id = run_id
        self.lock = threading.Lock()

    def write(self, event: str, status: str, **fields) -> str:
        if "run_id" in fields:
            raise ValueError("실행 식별자는 로그에서 지정합니다")
        with self.lock:
            timestamp = datetime.now(KST).isoformat(timespec="milliseconds")[11:23]
            message = json.dumps({"run_id": self.run_id, **fields}, ensure_ascii=True,
                                 allow_nan=False, separators=(",", ":"))
            line = f"[{timestamp}] ASSIGNER | {event} | {status} | {message}"
            self.file.write(line + "\n")
            self.file.flush()
        return line

    def close(self) -> None:
        with self.lock:
            self.file.close()
