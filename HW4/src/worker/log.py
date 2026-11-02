from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

KST = timezone(timedelta(hours=9))


class WorkerLog:
    def __init__(self, directory, run_id):
        self.directory, self.run_id = Path(directory), run_id
        self.k = None
        self.file = None
        self.pending = []

    def write(self, event, status, **fields):
        # 번호를 받기 전 로그도 나중에 쓸 수 있게 시간 순서대로 모아둠
        stamp = datetime.now(KST).strftime("%H:%M:%S.%f")[:-3]
        body = json.dumps({"run_id": self.run_id, **fields}, ensure_ascii=False, allow_nan=False)
        record = (stamp, event, status, body)
        if self.file is None:
            self.pending.append(record)
        else:
            self._write(record)

    def _write(self, record):
        stamp, event, status, body = record
        self.file.write(f"[{stamp}] WORKER{self.k} | {event} | {status} | {body}\n")
        self.file.flush()

    def bind(self, k):
        # 내 Worker 로그만 새로 만들고 같은 이름의 파일이 있으면 덮어쓰지 않음
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = (self.directory / f"Worker{k}.txt").open("x", encoding="utf-8", newline="\n")
        self.k = k
        for record in self.pending:
            self._write(record)
        self.pending.clear()

    def close(self):
        if self.file is not None:
            self.file.close()
