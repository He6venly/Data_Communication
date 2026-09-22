"""Master와 Worker의 실행 로그를 파일에 기록하는 모듈."""

import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def new_log_dir(role):
    """실행마다 새 경로를 만들어 이전 결과를 보존한다."""
    return f"logs/{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}/{role}"


VALID_NODES = {"Master", "Worker1", "Worker2", "Worker3", "Worker4"}
VALID_STATUS = {"INFO", "SUCCESS", "FAIL", "WARN"}
EVENT_DEFINITIONS = {
    # 통신 메시지 외에 노드 내부 이벤트와 최종 통계도 기록.
    "INIT": ("LOCAL", "노드 초기화"),
    "DISPATCH": ("LOCAL", "배정 직전 Worker별 부하, 제외 Worker, 직전 배정 Worker와 선택 결과. 최소 부하·동률 순환 근거이며 가상 통신비 없음"),
    "PROC": ("LOCAL", "작업 처리 시작과 성공·실패"),
    "REASSIGN": ("LOCAL", "실패 작업 우선 큐 등록 및 재할당"),
    "STAT": ("LOCAL", "최종 통계"),
    "COMM": ("Worker -> Master", "RECV 원문: 메시지 ID별 편도 비용 및 처리·대기시간 검증"),
    "HELLO": ("Worker -> Master", "Worker ID와 P2P 주소 등록"),
    "TASK": ("Master -> Worker", "작업 배정"),
    "TASK_ACK": ("Worker -> Master", "작업을 큐에 받았는지 확인"),
    "RESULT": ("Worker -> Master", "작업 성공 또는 실패 결과"),
    "QUEUE_STATUS": ("Worker -> Master", "현재 대기 작업 수"),
    "P2P_TRANSFER": ("Worker <-> Worker / Master <-> Worker", "작업 이전 및 P2P_CHECK·TIME_ACK·TRANSFER_CONFIRMED. id/source/target/key/attempt와 SEND·RECV 시각 기록"),
    "P2P_ACK": ("Worker -> Worker", "이전 작업 수신 확인"),
    "P2P_CHECK": ("LOCAL / Master <-> Worker", "부하 점검, 이웃 큐·중단 이유, 직접 통신 ID 비용 보고"),
    "STOP": ("Master -> Worker", "STOP 종료 요청, FINAL_STATS 최종 시간 통지(편도 비용 포함, 응답 없음)"),
    "STOP_ACK": ("Worker -> Master", "통계 저장과 종료 준비 완료"),
}


def initialize_log_files(log_dir="."):
    """새 실행을 위해 로그 파일과 이벤트 명세를 초기화한다."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # 기존 실행 결과가 있는 경로는 거부해 제출 로그 덮어쓰기를 방지한다.
    if any((log_dir / f"{node}.txt").exists() for node in VALID_NODES):
        raise FileExistsError(f"기존 로그가 있습니다. 새 --log-dir 경로를 지정하세요: {log_dir}")
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
            if self.file.closed:
                raise ValueError("이미 종료된 로그입니다")

            self.file.write(line)
            self.file.flush()

    def close(self):
        with self.lock:
            if self.file.closed:
                return

            self.file.flush()
            self.file.close()

    @staticmethod
    def _one_line(value: str) -> str:
        """줄바꿈 문자를 화면에 보이는 문자로 바꾼다."""
        return value.replace("\r", "\\r").replace("\n", "\\n")
