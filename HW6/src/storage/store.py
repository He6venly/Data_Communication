"""Peer의 파일과 청크 상태를 관리한다."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.common.contracts import (
    CommitResult,
    ConfigurationError,
    Env,
    EventSink,
    FileSnapshot,
    FileState,
    InvalidChunkError,
    LifecycleError,
    NoChunkError,
    NoFileError,
    OfflineError,
    Reservation,
    StoreIOError,
    StoreSnapshot,
)
from .positional import PositionalFile
from .results import save_results


@dataclass(slots=True)
class _File:
    """파일 하나의 메타정보와 다운로드 상태를 묶어 보관한다."""
    name: str
    size: int
    chunk_size: int
    origin: str
    sha256: str
    path: Path
    lock: threading.RLock = field(default_factory=threading.RLock)
    bitmap: list[bool] = field(default_factory=list)
    in_progress: set[int] = field(default_factory=set)
    prepared: bool = False
    state: FileState = FileState.DOWN
    handle: PositionalFile | None = None
    sent: int = 0
    distinct: set[int] = field(default_factory=set)
    sources: dict[str, int] = field(default_factory=dict)
    received_bytes: int = 0
    sent_bytes: int = 0
    hash_failures: int = 0
    reserved_sources: dict[int, Reservation] = field(default_factory=dict)
    committing: set[int] = field(default_factory=set)

    @property
    def nchunks(self) -> int:
        """마지막 청크가 짧아도 파일 크기 기준으로 청크 수를 올림 계산한다."""
        return (self.size + self.chunk_size - 1) // self.chunk_size

    def chunk_len(self, idx: int) -> int:
        """요청한 위치의 실제 길이를 계산해 마지막 청크를 자른다."""
        return min(self.chunk_size, self.size - idx * self.chunk_size)


class FileStore:
    """파일 단위 Lock과 예약 토큰으로 여러 worker의 접근을 조정한다."""

    def __init__(self, *, env: Env, peer_id: str, root: Path, emit: EventSink) -> None:
        """env에서 Peer 경로와 파일 메타정보를 읽고 메모리 상태를 만든다."""
        self._env = env
        self.peer_id = peer_id
        self.root = root.resolve()
        self._emit = emit
        self._lock = threading.RLock()
        self._files: dict[str, _File] = {}
        self._file_order: list[str] = []
        self._generation = 0
        self._paused = False
        self._initialized = False
        self._finalized = False
        self._serial = 0
        self._final_snapshot: StoreSnapshot | None = None
        self._tokens: dict[int, str] = {}
        self._released: set[int] = set()
        self._consumed: set[int] = set()
        peers = {str(p["id"]): p for p in env.get("peers", [])}
        if peer_id not in peers:
            raise ConfigurationError(f"env에 없는 peer: {peer_id}")
        self._peer = peers[peer_id]
        self._peer_dir = self._resolve_dir(self._peer["dir"])
        chunk_size = int(env["chunk_size"])
        if chunk_size <= 0:
            raise ConfigurationError("chunk_size는 양수여야 함")
        for item in env.get("files", []):
            name = str(item["name"])
            if not name or Path(name).name != name or name in (".", ".."):
                raise ConfigurationError(f"잘못된 파일 이름: {name}")
            file = _File(
                name=name,
                size=int(item["size"]),
                chunk_size=chunk_size,
                origin=str(item["origin"]),
                sha256=str(item["sha256"]).lower(),
                path=self._peer_dir / name,
            )
            if file.size <= 0 or len(file.sha256) != 64:
                raise ConfigurationError(f"잘못된 파일 메타정보: {name}")
            self._files[name] = file
            self._file_order.append(name)

    def _resolve_dir(self, value: str) -> Path:
        """절대 경로는 유지하고 상대 경로는 작업 루트에 붙인다."""
        path = Path(value)
        return path.resolve() if path.is_absolute() else (self.root / path).resolve()

    def _require_initialized(self) -> None:
        """초기화 전이나 최종 종료 뒤의 상태 변경 요청을 거부한다."""
        if not self._initialized or self._finalized:
            raise LifecycleError("FileStore가 초기화되지 않았거나 이미 종료됨")

    @staticmethod
    def _hash(path: Path) -> str:
        """대용량 파일을 한 번에 메모리에 올리지 않고 SHA-256을 계산한다."""
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest()

    def initialize(self) -> None:
        """원본 파일의 크기·해시를 확인하고 원본 청크만 보유 처리한다."""
        with self._lock:
            if self._finalized:
                raise LifecycleError("종료된 FileStore를 다시 초기화할 수 없음")
            if self._initialized:
                return
            opened: list[_File] = []
            try:
                self._peer_dir.mkdir(parents=True, exist_ok=True)
                for file in self._files.values():
                    file.bitmap = [False] * file.nchunks
                    file.in_progress.clear()
                    file.prepared = False
                    file.state = FileState.DOWN
                    if file.origin == self.peer_id:
                        if not file.path.is_file() or file.path.stat().st_size != file.size:
                            raise ConfigurationError(f"원본 파일 크기 오류: {file.name}")
                        if self._hash(file.path) != file.sha256:
                            raise ConfigurationError(f"원본 SHA-256 오류: {file.name}")
                        file.handle = PositionalFile(file.path, writable=False)
                        opened.append(file)
                        file.bitmap = [True] * file.nchunks
                        file.prepared = True
                        file.state = FileState.SEED
                self._initialized = True
            except ConfigurationError:
                for file in opened:
                    if file.handle:
                        file.handle.close()
                        file.handle = None
                raise
            except OSError as exc:
                for file in opened:
                    if file.handle:
                        file.handle.close()
                        file.handle = None
                raise StoreIOError(str(exc), operation="initialize") from exc

    def _snapshot_file(self, file: _File) -> FileSnapshot:
        """내부의 가변 상태를 읽기 전용 FileSnapshot으로 복사한다."""
        return FileSnapshot(
            name=file.name,
            size=file.size,
            chunk_size=file.chunk_size,
            nchunks=file.nchunks,
            origin=file.origin,
            sha256=file.sha256,
            state=file.state,
            prepared=file.prepared,
            bitmap="".join("1" if bit else "0" for bit in file.bitmap),
            in_progress=tuple(sorted(file.in_progress)),
            sent=file.sent,
            distinct=len(file.distinct),
            sources=tuple(sorted(file.sources.items())),
            received_bytes=file.received_bytes,
            sent_bytes=file.sent_bytes,
            hash_failures=file.hash_failures,
        )

    def _snapshot_locked(self) -> StoreSnapshot:
        """한 시점의 파일별 bitmap과 누적 통계를 함께 복사한다."""
        file_list: list[FileSnapshot] = []
        for name in self._file_order:
            item = self._files[name]
            with item.lock:
                file_list.append(self._snapshot_file(item))
        files = tuple(file_list)
        downloaded = sum(
            snap.bitmap.count("1") for snap in files if snap.origin != self.peer_id
        )
        return StoreSnapshot(
            peer_id=self.peer_id,
            generation=self._generation,
            paused=self._paused,
            downloaded_have=downloaded,
            received_bytes=sum(f.received_bytes for f in files),
            sent_bytes=sum(f.sent_bytes for f in files),
            files=files,
        )

    def snapshot(self) -> StoreSnapshot:
        """현재 저장소 상태를 외부에서 수정할 수 없는 형태로 돌려준다."""
        with self._lock:
            if not self._initialized and not self._finalized:
                raise LifecycleError("초기화 전 snapshot")
            return self._snapshot_locked()

    def prepare_download(self, file: str) -> FileSnapshot:
        """받을 파일의 전체 크기 .part를 준비하고 bitmap을 0으로 초기화한다."""
        with self._lock:
            self._require_initialized()
            item = self._files.get(file)
            if item is None:
                raise NoFileError(f"알 수 없는 파일: {file}", file=file)
            with item.lock:
                if item.prepared or item.state == FileState.SEED:
                    return self._snapshot_file(item)
                try:
                    item.path.parent.mkdir(parents=True, exist_ok=True)
                    part_path = item.path.with_name(item.path.name + ".part")
                    if not part_path.exists():
                        with part_path.open("wb") as stream:
                            stream.truncate(item.size)
                    elif part_path.stat().st_size != item.size:
                        with part_path.open("r+b") as stream:
                            stream.truncate(item.size)
                    item.handle = PositionalFile(part_path, writable=True, size=item.size)
                    item.bitmap = [False] * item.nchunks
                    item.prepared = True
                    item.state = FileState.DOWN
                    return self._snapshot_file(item)
                except OSError as exc:
                    raise StoreIOError(str(exc), operation="prepare", file=file) from exc

    def reserve(self, file: str, idx: int) -> Reservation | None:
        """보유·진행 중 청크를 건너뛰고 새 작업을 세대 토큰으로 예약한다."""
        if type(idx) is not int:
            raise TypeError("idx는 int여야 함")
        with self._lock:
            self._require_initialized()
            item = self._files.get(file)
            if item is None:
                raise NoFileError(f"알 수 없는 파일: {file}", file=file)
            with item.lock:
                if idx < 0 or idx >= item.nchunks:
                    raise InvalidChunkError(f"잘못된 청크 번호: {idx}", file=file)
                if self._paused or not item.prepared or item.state != FileState.DOWN:
                    return None
                if item.bitmap[idx] or idx in item.in_progress:
                    return None
                self._serial += 1
                token = Reservation(file=file, idx=idx, generation=self._generation, serial=self._serial)
                item.in_progress.add(idx)
                item.reserved_sources[token.serial] = token
                self._tokens[token.serial] = file
                return token

    def _expected_token(self, token: Reservation) -> _File:
        """토큰이 이 저장소에서 발급되었는지 확인하고 파일을 찾는다."""
        if not isinstance(token, Reservation):
            raise TypeError("token은 Reservation이어야 함")
        file_name = self._tokens.get(token.serial)
        if file_name is None or file_name != token.file:
            if token.serial in self._released:
                raise InvalidChunkError("이미 해제된 예약", file=token.file)
            if token.serial in self._consumed:
                raise InvalidChunkError("이미 사용된 예약", file=token.file)
            raise InvalidChunkError("발급되지 않은 예약", file=token.file)
        return self._files[file_name]

    def commit(self, token: Reservation, data: bytes, src: str) -> CommitResult:
        """위치 쓰기가 끝난 청크만 bitmap에 공개하고 마지막엔 전체 해시를 확인한다."""
        if not isinstance(data, bytes) or not isinstance(src, str):
            raise TypeError("data는 bytes, src는 str이어야 함")
        ev_recv: dict[str, Any] | None = None
        ev_hash: dict[str, Any] | None = None
        ev_corrupt: dict[str, Any] | None = None
        verify_error: StoreIOError | None = None
        complete_now = False
        with self._lock:
            self._require_initialized()
            item = self._expected_token(token)
            with item.lock:
                if token.idx < 0 or token.idx >= item.nchunks:
                    raise InvalidChunkError("예약 청크 번호 오류", file=item.name)
                if len(data) != item.chunk_len(token.idx):
                    raise InvalidChunkError("청크 본문 길이 오류", file=item.name)
                if token.generation != self._generation:
                    return CommitResult(accepted=False, state=item.state, complete_now=False, reason="STALE")
                if self._paused or item.reserved_sources.get(token.serial) != token:
                    reason = "RELEASED" if token.serial in self._released else "CONSUMED"
                    return CommitResult(accepted=False, state=item.state, complete_now=False, reason=reason)
                if token.serial in item.committing:
                    return CommitResult(accepted=False, state=item.state, complete_now=False, reason="CONSUMED")
                item.committing.add(token.serial)
                handle = item.handle
                offset = token.idx * item.chunk_size
        # 파일 쓰기가 끝나기 전에는 bitmap을 바꾸지 않아 업로드가 빈 청크를 읽지 않게 한다.
        try:
            if handle is None:
                raise OSError("다운로드 파일 핸들이 없음")
            handle.write(offset, data)
        except OSError as exc:
            with self._lock:
                with item.lock:
                    item.committing.discard(token.serial)
                    item.reserved_sources.pop(token.serial, None)
                    item.in_progress.discard(token.idx)
                    self._released.add(token.serial)
            raise StoreIOError(str(exc), operation="commit", file=item.name) from exc

        # 쓰는 동안 세대가 바뀌었다면 디스크 바이트는 두되 보유 상태에는 반영하지 않는다.
        with self._lock:
            with item.lock:
                item.committing.discard(token.serial)
                if token.generation != self._generation or self._paused:
                    item.reserved_sources.pop(token.serial, None)
                    item.in_progress.discard(token.idx)
                    self._released.add(token.serial)
                    return CommitResult(accepted=False, state=item.state, complete_now=False, reason="STALE")
                if item.reserved_sources.get(token.serial) != token:
                    item.in_progress.discard(token.idx)
                    self._released.add(token.serial)
                    return CommitResult(accepted=False, state=item.state, complete_now=False, reason="RELEASED")
                item.reserved_sources.pop(token.serial, None)
                item.in_progress.discard(token.idx)
                item.bitmap[token.idx] = True
                item.received_bytes += len(data)
                item.sources[src] = item.sources.get(src, 0) + 1
                self._consumed.add(token.serial)
                ev_recv = {"file": item.name, "idx": token.idx, "src": src}
                if all(item.bitmap):
                    item.state = FileState.VERIFYING
                    complete_now = True
                result = CommitResult(accepted=True, state=item.state, complete_now=False, reason=None)
        if complete_now:
            with item.lock:
                try:
                    complete_now, elapsed, ev_corrupt = self._verify_complete(item)
                    ev_hash = {"file": item.name, "ok": complete_now, "sec": elapsed}
                except StoreIOError as exc:
                    verify_error = exc
                result = CommitResult(accepted=True, state=item.state, complete_now=complete_now, reason=None)
        self._emit("RECV", **ev_recv)
        if ev_hash is not None:
            self._emit("HASH", **ev_hash)
        if ev_corrupt is not None:
            self._emit("CORRUPT", **ev_corrupt)
        if verify_error is not None:
            raise verify_error
        return result

    def _verify_complete(self, item: _File) -> tuple[bool, float, dict[str, Any] | None]:
        """완성 파일의 해시를 비교해 SEED 전환 또는 재수신 상태를 결정한다."""
        part_path = item.path.with_name(item.path.name + ".part")
        started = time.monotonic()
        corrupt_event: dict[str, Any] | None = None
        try:
            if item.handle is not None:
                item.handle.flush()
                item.handle.close()
                item.handle = None
            actual = self._hash(part_path)
            if actual == item.sha256:
                os.replace(part_path, item.path)
                item.handle = PositionalFile(item.path, writable=False)
                item.state = FileState.SEED
                item.hash_failures = 0
                return True, time.monotonic() - started, None
            item.hash_failures += 1
            item.bitmap = [False] * item.nchunks
            item.in_progress.clear()
            item.sources.clear()
            item.state = FileState.DOWN if item.hash_failures < 2 else FileState.FAILED
            if item.hash_failures < 2:
                with part_path.open("wb") as stream:
                    stream.truncate(item.size)
                item.handle = PositionalFile(part_path, writable=True, size=item.size)
                corrupt_event = {"file": item.name, "action": "redownload", "tries": item.hash_failures}
            else:
                corrupt = item.path.with_name(item.path.name + ".corrupt")
                if part_path.exists():
                    os.replace(part_path, corrupt)
                corrupt_event = {"file": item.name, "action": "give_up", "tries": item.hash_failures}
            return False, time.monotonic() - started, corrupt_event
        except OSError as exc:
            item.state = FileState.FAILED
            raise StoreIOError(str(exc), operation="hash", file=item.name) from exc

    def release(self, token: Reservation) -> None:
        """워커 종료 시 미완료 예약을 안전하게 풀어 다시 선택할 수 있게 한다."""
        if not isinstance(token, Reservation):
            raise TypeError("token은 Reservation이어야 함")
        with self._lock:
            file_name = self._tokens.get(token.serial)
            if file_name is None:
                return
            item = self._files[file_name]
            with item.lock:
                if item.reserved_sources.pop(token.serial, None) is not None:
                    item.in_progress.discard(token.idx)
                    self._released.add(token.serial)

    def read_chunk(self, file: str, idx: int) -> bytes:
        """bitmap에 공개된 청크만 정확한 길이로 읽어 업로드에 전달한다."""
        if type(idx) is not int:
            raise TypeError("idx는 int여야 함")
        with self._lock:
            self._require_initialized()
            item = self._files.get(file)
            if item is None:
                raise NoFileError(f"알 수 없는 파일: {file}", file=file)
            if self._paused:
                raise OfflineError("Peer가 오프라인 상태임", file=file)
        with item.lock:
            if idx < 0 or idx >= item.nchunks:
                raise InvalidChunkError(f"잘못된 청크 번호: {idx}", file=file)
            if not item.prepared or item.state == FileState.VERIFYING or not item.bitmap[idx] or item.handle is None:
                raise NoChunkError("청크를 보유하지 않음", file=file)
            try:
                data = item.handle.read(idx * item.chunk_size, item.chunk_len(idx))
            except OSError as exc:
                raise StoreIOError(str(exc), operation="read", file=file) from exc
            if len(data) != item.chunk_len(idx):
                raise StoreIOError("파일에서 짧은 청크를 읽음", operation="read", file=file)
            return data

    def record_sent(self, file: str, idx: int, size: int) -> None:
        """전체 DATA 송신이 끝난 뒤에만 파일별 전송 횟수와 바이트를 누적한다."""
        if type(idx) is not int or type(size) is not int:
            raise TypeError("idx와 size는 int여야 함")
        with self._lock:
            self._require_initialized()
            item = self._files.get(file)
            if item is None:
                raise NoFileError(f"알 수 없는 파일: {file}", file=file)
            with item.lock:
                if idx < 0 or idx >= item.nchunks or size != item.chunk_len(idx):
                    raise InvalidChunkError("전송 청크 크기 오류", file=file)
                item.sent += 1
                item.distinct.add(idx)
                item.sent_bytes += size

    def set_stalled(self, file: str, stalled: bool) -> bool:
        """다운로드 파일의 DOWN/STALLED 전환 여부를 알려준다."""
        with self._lock:
            self._require_initialized()
            item = self._files.get(file)
            if item is None:
                raise NoFileError(f"알 수 없는 파일: {file}", file=file)
            with item.lock:
                if item.state not in (FileState.DOWN, FileState.STALLED):
                    return False
                target = FileState.STALLED if stalled else FileState.DOWN
                if item.state == target:
                    return False
                item.state = target
                return True

    def pause(self) -> None:
        """첫 오프라인 전환에서 세대를 올리고 진행 중인 예약을 무효화한다."""
        with self._lock:
            self._require_initialized()
            if self._paused:
                return
            self._paused = True
            self._generation += 1
            for item in self._files.values():
                with item.lock:
                    item.in_progress.clear()
                    item.reserved_sources.clear()

    def resume(self) -> None:
        """중단된 Peer를 새 세대로 열고 기존 bitmap과 통계는 유지한다."""
        with self._lock:
            self._require_initialized()
            if not self._paused:
                return
            self._paused = False

    def finalize(self) -> StoreSnapshot:
        """누락 청크를 0으로 정리하고 bitmap·lost·incomplete 결과를 저장한다."""
        with self._lock:
            if self._finalized:
                assert self._final_snapshot is not None
                return self._final_snapshot
            self._require_initialized()
            self._paused = True
            for item in self._files.values():
                with item.lock:
                    if item.origin != self.peer_id and item.state != FileState.SEED:
                        if not item.prepared and item.state != FileState.FAILED:
                            self.prepare_download(item.name)
                        part_path = item.path.with_name(item.path.name + ".part")
                        if item.state != FileState.FAILED and not part_path.exists():
                            with part_path.open("wb") as stream:
                                stream.truncate(item.size)
                            item.bitmap = [False] * item.nchunks
                            item.state = FileState.DOWN
                            item.handle = PositionalFile(part_path, writable=True, size=item.size)
                        if item.handle is not None:
                            try:
                                item.handle.flush()
                                item.handle.close()
                            except OSError as exc:
                                raise StoreIOError(str(exc), operation="finalize", file=item.name) from exc
                            item.handle = None
                        missing = [i for i, have in enumerate(item.bitmap) if not have]
                        try:
                            if missing and part_path.exists() and item.state != FileState.FAILED:
                                with part_path.open("r+b") as stream:
                                    zero = bytes(min(item.chunk_size, 1024 * 1024))
                                    for idx in missing:
                                        length = item.chunk_len(idx)
                                        stream.seek(idx * item.chunk_size)
                                        stream.write(zero[:length])
                            if part_path.exists() and item.state != FileState.FAILED:
                                incomplete = item.path.with_name(item.path.name + ".incomplete")
                                os.replace(part_path, incomplete)
                                item.path = incomplete
                            sidecar = item.path.with_name(item.path.name.removesuffix(".incomplete"))
                            save_results(sidecar, "".join("1" if bit else "0" for bit in item.bitmap))
                        except OSError as exc:
                            raise StoreIOError(str(exc), operation="finalize", file=item.name) from exc
                    if item.handle is not None:
                        try:
                            item.handle.close()
                        except OSError as exc:
                            raise StoreIOError(str(exc), operation="finalize", file=item.name) from exc
                        item.handle = None
                    if item.origin == self.peer_id or item.state == FileState.SEED:
                        save_results(item.path, "".join("1" if bit else "0" for bit in item.bitmap))
            self._finalized = True
            self._final_snapshot = self._snapshot_locked()
            return self._final_snapshot\n