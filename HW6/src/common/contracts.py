"""HW6의 공유 자료형·예외·인터페이스. 네트워크·파일 I/O는 구현하지 않음."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Any, Callable, Literal, Mapping, Protocol, TextIO, TypeAlias


Env: TypeAlias = Mapping[str, Any]
JSONValue: TypeAlias = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)
RejectReason: TypeAlias = Literal["STALE", "RELEASED", "CONSUMED"]


class HW6Error(Exception):
    """구성요소 사이에 오류 종류와 발생 위치를 전달함."""

    def __init__(
        self, message: str, *, operation: str = "", file: str | None = None
    ) -> None:
        """오류 메시지·작업 종류·대상 파일을 함께 보관함."""
        super().__init__(message)
        self.operation = operation
        self.file = file


class ConfigurationError(HW6Error):
    """env·인자·원본 검증 실패."""


class NoFileError(HW6Error):
    """env에 없는 파일."""


class NoChunkError(HW6Error):
    """정상 범위의 청크가 아직 없음."""


class InvalidChunkError(HW6Error):
    """청크 번호·본문 크기가 계약과 다름."""


class OfflineError(HW6Error):
    """가상 오프라인 중의 업로드 읽기."""


class StoreIOError(HW6Error):
    """실행 중 파일·매핑·저장 I/O 실패."""


class LifecycleError(HW6Error):
    """초기화 전·최종 종료 후 등 잘못된 호출 순서."""


class ShutdownError(HW6Error):
    """정해진 대기 뒤에도 구성요소가 종료되지 않음."""


class ConnClosed(ConnectionError):
    """줄·본문이 완성되기 전에 연결이 닫힘."""


class FileState(str, Enum):
    """파일의 수신·검증·완료·유실 상태를 구분함."""

    DOWN = "DOWN"
    VERIFYING = "VERIFYING"
    SEED = "SEED"
    STALLED = "STALLED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True, kw_only=True)
class Reservation:
    """파일·청크·세대로 다운로드 예약을 식별함."""

    file: str
    idx: int
    generation: int
    serial: int


@dataclass(frozen=True, slots=True, kw_only=True)
class FileSnapshot:
    """파일별 보유 상태와 전송 통계를 읽기 전용으로 전달함."""

    name: str
    size: int
    chunk_size: int
    nchunks: int
    origin: str
    sha256: str
    state: FileState
    prepared: bool
    bitmap: str
    in_progress: tuple[int, ...]
    sent: int
    distinct: int
    sources: tuple[tuple[str, int], ...]
    received_bytes: int
    sent_bytes: int
    hash_failures: int


@dataclass(frozen=True, slots=True, kw_only=True)
class StoreSnapshot:
    """Peer 전체의 파일 상태와 누적 전송량을 전달함."""

    peer_id: str
    generation: int
    paused: bool
    downloaded_have: int
    received_bytes: int
    sent_bytes: int
    files: tuple[FileSnapshot, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CommitResult:
    """수신 반영 여부와 파일 완성 전환을 호출자에게 알림."""

    accepted: bool
    state: FileState
    complete_now: bool
    reason: RejectReason | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PeerView:
    """상태판에 필요한 Peer 정보·속도·파일 상태를 전달함."""

    peer_id: str
    elapsed_sec: float
    online: bool
    policy: Literal["random", "rarest"]
    up_kbps: int
    down_kbps: int
    actual_up_kbps: float
    actual_down_kbps: float
    files: tuple[FileSnapshot, ...]


class EventSink(Protocol):
    """구성요소의 이벤트를 같은 로그 작성자에게 전달하는 규약임."""

    def __call__(self, ev: str, **fields: JSONValue) -> None: ...


class EventLogPort(Protocol):
    """로그 기록·최근 이벤트 조회·종료의 공통 호출 규약임."""

    def __init__(
        self, *, peer_id: str, root: Path, started_at: float
    ) -> None: ...

    def event(self, ev: str, **fields: JSONValue) -> None: ...

    def recent(self, n: int = 5) -> tuple[str, ...]: ...

    def close(self) -> None: ...


class StorePort(Protocol):
    """Peer와 업로드 서버가 사용하는 저장소 호출 규약임."""

    def __init__(
        self, *, env: Env, peer_id: str, root: Path, emit: EventSink
    ) -> None: ...

    def initialize(self) -> None: ...

    def snapshot(self) -> StoreSnapshot: ...

    def prepare_download(self, file: str) -> FileSnapshot: ...

    def reserve(self, file: str, idx: int) -> Reservation | None: ...

    def commit(self, token: Reservation, data: bytes, src: str) -> CommitResult: ...

    def release(self, token: Reservation) -> None: ...

    def read_chunk(self, file: str, idx: int) -> bytes: ...

    def record_sent(self, file: str, idx: int, size: int) -> None: ...

    def set_stalled(self, file: str, stalled: bool) -> bool: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def finalize(self) -> StoreSnapshot: ...


class UploadPort(Protocol):
    """업로드 서버의 기동·가상 장애·종료 호출 규약임."""

    def __init__(
        self,
        *,
        env: Env,
        peer_id: str,
        store: StorePort,
        stopping: Event,
        emit: EventSink,
    ) -> None: ...

    def start(self) -> None: ...

    def offline(self) -> None: ...

    def online(self) -> None: ...

    def stop(self, grace_sec: float = 3.0) -> None: ...


class ScreenPort(Protocol):
    """복사본과 최근 이벤트로 상태판을 갱신하는 호출 규약임."""

    def __init__(
        self, *, stopping: Event, period_sec: float, stream: TextIO | None = None
    ) -> None: ...

    def start(
        self,
        snapshot: Callable[[], PeerView],
        recent: Callable[[int], tuple[str, ...]],
    ) -> None: ...

    def stop(self) -> None: ...
