"""Master와 Worker의 실행 로그를 파일에 기록하는 모듈."""

import threading
from pathlib import Path


VALID_NODES = {"Master", "Worker1", "Worker2", "Worker3", "Worker4"}
VALID_STATUS = {"INFO", "SUCCESS", "FAIL", "WARN"}


class NodeLogger:
    """노드 하나의 로그 파일을 관리한다."""

    definition_lock = threading.Lock()

    def __init__(self, node: str, log_dir="."):
        if node not in VALID_NODES:
            raise ValueError(f"올바르지 않은 노드 이름입니다: {node}")

        self.node = node
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.closed = False

        log_path = self.log_dir / f"{node}.txt"
        self.file = log_path.open("a", encoding="utf-8", buffering=1)

    def log(self, clock, event: str, status: str, message: str):
        """가상 시각과 이벤트 내용을 한 줄로 기록한다."""
        if not event or not isinstance(event, str):
            raise ValueError("event는 비어 있지 않은 문자열이어야 합니다")

        if status not in VALID_STATUS:
            raise ValueError(f"올바르지 않은 상태값입니다: {status}")

        # 줄바꿈이 들어와도 로그 한 건은 파일의 한 줄만 사용한다.
        safe_event = self._one_line(event)
        safe_message = self._one_line(str(message))
        safe_clock = self._one_line(str(clock))
        line = (
            f"[{safe_clock}] {self.node} | {safe_event} | "
            f"{status} | {safe_message}\n"
        )

        # 여러 스레드의 로그가 서로 섞이지 않게 한 번에 기록한다.
        with self.lock:
            if self.closed:
                raise ValueError("이미 종료된 로그입니다")

            self.file.write(line)
            self.file.flush()

    def define_event(self, event: str, description: str):
        """이벤트 이름과 설명을 AllDefinedLogs.txt에 기록한다."""
        if not event or not isinstance(event, str):
            raise ValueError("event는 비어 있지 않은 문자열이어야 합니다")

        safe_event = self._one_line(event)
        safe_description = self._one_line(str(description))
        definition_path = self.log_dir / "AllDefinedLogs.txt"

        with NodeLogger.definition_lock:
            with definition_path.open("a", encoding="utf-8") as file:
                file.write(f"{safe_event} | {safe_description}\n")

    def close(self):
        """남은 내용을 저장하고 로그 파일을 닫는다."""
        with self.lock:
            if self.closed:
                return

            self.file.flush()
            self.file.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @staticmethod
    def _one_line(value: str) -> str:
        """줄바꿈 문자를 화면에 보이는 문자로 바꾼다."""
        return value.replace("\r", "\\r").replace("\n", "\\n")


# Master 사용 예제
#   with NodeLogger("Master", "logs") as logger:
#       logger.define_event("WORKER_CONNECT", "Worker가 Master에 접속")
#       logger.log(0, "WORKER_CONNECT", "SUCCESS", "Worker1 접속 완료")
#       logger.log(1, "TASK_SEND", "INFO", "Key=0A1F, Worker=1")
#
# logs/Master.txt 출력값
#   [0] Master | WORKER_CONNECT | SUCCESS | Worker1 접속 완료
#   [1] Master | TASK_SEND | INFO | Key=0A1F, Worker=1
#
# logs/AllDefinedLogs.txt 출력값
#   WORKER_CONNECT | Worker가 Master에 접속
#
# Worker 사용 예제
#   logger = NodeLogger("Worker1", "logs")
#   logger.log(2, "QUEUE_STATUS", "WARN", "대기 작업 수=8")
#   logger.close()
#
# logs/Worker1.txt 출력값
#   [2] Worker1 | QUEUE_STATUS | WARN | 대기 작업 수=8
