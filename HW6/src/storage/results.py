"""bitmap과 .lost 결과를 저장하는 함수."""

from __future__ import annotations

from pathlib import Path


def lost_ranges(bitmap: str) -> str:
    """0인 인덱스를 오름차순 단일 번호와 연속 구간으로 압축한다."""
    missing = [i for i, bit in enumerate(bitmap) if bit == "0"]
    if not missing:
        return ""
    ranges: list[str] = []
    start = previous = missing[0]
    for idx in missing[1:]:
        if idx != previous + 1:
            ranges.append(str(start) if start == previous else f"{start}-{previous}")
            start = idx
        previous = idx
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def save_results(path: Path, bitmap: str) -> None:
    """마지막 bitmap을 LF 없이 쓰고, 미완성일 때만 lost를 남긴다."""
    path.with_name(path.name + ".bitmap").write_text(bitmap, encoding="ascii")
    lost_path = path.with_name(path.name + ".lost")
    missing = lost_ranges(bitmap)
    if missing:
        lost_path.write_text(missing, encoding="ascii")
    elif lost_path.exists():
        lost_path.unlink()\n