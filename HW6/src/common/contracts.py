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
    def __init__(
        self, message: str, *, operation: str = "", file: str | None = None
    ) -> None:
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
    DOWN = "DOWN"
    VERIFYING = "VERIFYING"
    SEED = "SEED"
    STALLED = "STALLED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True, kw_only=True)
class Reservation:
    file: str
    idx: int
    generation: int
    serial: int


@dataclass(frozen=True, slots=True, kw_only=True)
class FileSnapshot:
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
    peer_id: str
    generation: int
    paused: bool
    downloaded_have: int
    received_bytes: int
    sent_bytes: int
    files: tuple[FileSnapshot, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CommitResult:
    accepted: bool
    state: FileState
    complete_now: bool
    reason: RejectReason | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PeerView:
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
    def __call__(self, ev: str, **fields: JSONValue) -> None: ...


class EventLogPort(Protocol):
    def __init__(
        self, *, peer_id: str, root: Path, started_at: float
    ) -> None: ...

    def event(self, ev: str, **fields: JSONValue) -> None: ...

    def recent(self, n: int = 5) -> tuple[str, ...]: ...

    def close(self) -> None: ...


class StorePort(Protocol):
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
    def __init__(
        self, *, stopping: Event, period_sec: float, stream: TextIO | None = None
    ) -> None: ...

    def start(
        self,
        snapshot: Callable[[], PeerView],
        recent: Callable[[int], tuple[str, ...]],
    ) -> None: ...

    def stop(self) -> None: ...
