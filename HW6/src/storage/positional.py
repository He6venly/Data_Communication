"""파일 위치를 명시해 읽고 쓰는 작은 도우미."""

from __future__ import annotations

import mmap
import os
from pathlib import Path


class PositionalFile:
    """Linux에서는 pread/pwrite, Windows에서는 mmap으로 접근한다."""

    def __init__(self, path: Path, *, writable: bool, size: int | None = None) -> None:
        """운영체제에 맞는 위치 지정 접근 핸들을 열고 선택적으로 크기를 맞춘다."""
        self.path = path
        self.writable = writable
        self._fd: int | None = None
        self._file = None
        self._map: mmap.mmap | None = None
        if os.name == "nt":
            mode = "r+b" if writable else "rb"
            self._file = path.open(mode)
            if size is not None and writable:
                self._file.truncate(size)
                self._file.flush()
            length = path.stat().st_size
            if length:
                access = mmap.ACCESS_WRITE if writable else mmap.ACCESS_READ
                self._map = mmap.mmap(self._file.fileno(), length, access=access)
        else:
            flags = os.O_RDWR if writable else os.O_RDONLY
            self._fd = os.open(path, flags)
            if size is not None and writable:
                os.ftruncate(self._fd, size)

    def read(self, offset: int, length: int) -> bytes:
        """현재 파일 오프셋을 공유하지 않고 지정한 바이트 구간을 읽는다."""
        if self._map is not None:
            return self._map[offset : offset + length]
        if self._fd is None:
            raise ValueError("파일이 닫혀 있음")
        if hasattr(os, "pread"):
            return os.pread(self._fd, length, offset)
        os.lseek(self._fd, offset, os.SEEK_SET)
        return os.read(self._fd, length)

    def write(self, offset: int, data: bytes) -> None:
        """pread/pwrite 또는 mmap으로 지정 위치에만 청크 바이트를 쓴다."""
        if not self.writable:
            raise ValueError("읽기 전용 파일")
        if self._map is not None:
            self._map[offset : offset + len(data)] = data
            return
        if self._fd is None:
            raise ValueError("파일이 닫혀 있음")
        if hasattr(os, "pwrite"):
            written = os.pwrite(self._fd, data, offset)
        else:
            os.lseek(self._fd, offset, os.SEEK_SET)
            written = os.write(self._fd, data)
        if written != len(data):
            raise OSError(f"짧은 위치 쓰기: {written}/{len(data)}")

    def flush(self) -> None:
        """해시 검사나 종료 전에 매핑·파일 버퍼를 반영한다."""
        if self._map is not None:
            self._map.flush()
        elif self._fd is not None:
            os.fsync(self._fd)

    def close(self) -> None:
        """rename 전에 매핑과 파일 핸들을 모두 닫는다."""
        if self._map is not None:
            self._map.close()
            self._map = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self._file is not None:
            self._file.close()
            self._file = None
