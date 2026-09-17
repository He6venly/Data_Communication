"""Master와 Worker의 실행 로그를 파일에 기록하는 모듈."""

import threading
from pathlib import Path


VALID_NODES = {"Master", "Worker1", "Worker2", "Worker3", "Worker4"}
VALID_STATUS = {"INFO", "SUCCESS", "FAIL", "WARN"}
EVENT_DEFINITIONS = {
    "HELLO": ("Worker -> Master", "Worker ID와 P2P 주소 등록"),
    "TASK": ("Master -> Worker", "작업 배정"),
    "TASK_ACK": ("Worker -> Master", "작업을 큐에 받았는지 확인"),
    "RESULT": ("Worker -> Master", "작업 성공 또는 실패 결과"),
    "QUEUE_STATUS": ("Worker -> Master", "현재 대기 작업 수"),
    "P2P_TRANSFER": ("Worker -> Worker", "대기 작업 이전"),
    "P2P_ACK": ("Worker -> Worker", "이전 작업 수신 확인"),
    "STOP": ("Master -> Worker", "종료 요청"),
    "STOP_ACK": ("Worker -> Master", "통계 저장과 종료 준비 완료"),
}


def initialize_log_files(log_dir="."):
    """새 실행을 위해 로그 파일과 이벤트 명세를 초기화한다."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # 이전 실행의 노드별 로그를 모두 비운다.
    for node in VALID_NODES:
        log_path = log_dir / f"{node}.txt"
        log_path.write_text("", encoding="utf-8")

    # 중앙 명세를 기준으로 매번 새 파일을 만들어 중복을 막는다.
    definition_path = log_dir / "AllDefinedLogs.txt"
    with definition_path.open("w", encoding="utf-8") as file:
        for event, (direction, description) in EVENT_DEFINITIONS.items():
            file.write(f"{event} | {direction} | {description}\n")


class NodeLogger:
    """노드 하나의 로그 파일을 관리한다."""

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

        if event not in EVENT_DEFINITIONS:
            raise ValueError(f"명세에 등록되지 않은 이벤트입니다: {event}")

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


# 실행 시작 시 한 번만 호출하여 이전 로그와 이벤트 명세를 초기화한다.
#   initialize_log_files("logs")
#
# Master 사용 예제
#   with NodeLogger("Master", "logs") as logger:
#       logger.log(0, "HELLO", "SUCCESS", "Worker1 접속 완료")
#       logger.log(1, "TASK", "INFO", "Key=0A1F, Worker=1")
#
# logs/Master.txt 출력값
#   [0] Master | HELLO | SUCCESS | Worker1 접속 완료
#   [1] Master | TASK | INFO | Key=0A1F, Worker=1
#
# logs/AllDefinedLogs.txt 출력값 일부
#   HELLO | Worker -> Master | Worker ID와 P2P 주소 등록
#   TASK | Master -> Worker | 작업 배정
#
# Worker 사용 예제
#   logger = NodeLogger("Worker1", "logs")
#   logger.log(2, "QUEUE_STATUS", "WARN", "대기 작업 수=8")
#   logger.close()
#
# logs/Worker1.txt 출력값
#   [2] Worker1 | QUEUE_STATUS | WARN | 대기 작업 수=8
