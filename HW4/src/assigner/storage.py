"""입력 그림의 형식을 검사하고 원본 해시를 보관한다."""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from collections.abc import Callable

WIDTH = 160
HEIGHT = 80


@dataclass(frozen=True)
class Canvas:
    rows: tuple[str, ...]
    sha256: str


def read_canvas(path: Path) -> Canvas:
    data = path.read_bytes()
    # 공백도 그림의 일부이므로 줄바꿈만 분리해 원본을 검사한다.
    rows = data.split(b"\n")
    if len(rows) != HEIGHT + 1 or rows[-1] != b"":
        raise ValueError(f"{path}: 80줄과 마지막 줄바꿈이 필요합니다")
    if any(len(row) != WIDTH or any(c < 32 or c > 126 for c in row)
           for row in rows[:-1]):
        raise ValueError(f"{path}: 각 줄은 출력 가능한 ASCII 160자여야 합니다")
    return Canvas(tuple(row.decode("ascii") for row in rows[:-1]),
                  sha256(data).hexdigest())


def read_canvases(directory: Path) -> tuple[Canvas, Canvas, Canvas]:
    return tuple(read_canvas(directory / f"canvas{i}.txt") for i in range(3))


class RunStorage:
    def __init__(self, directory: Path, run_info: dict,
                 on_save: Callable[[dict], None] | None = None):
        self.directory = directory
        self.on_save = on_save
        self.next_snapshot = 0
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            raise FileExistsError(f"{directory}: 출력 폴더가 비어 있지 않습니다")
        # 실행 정보를 먼저 선점해 기존 결과와 새 결과가 섞이지 않게 한다.
        with (directory / "run_info.json").open("x", encoding="utf-8", newline="\n") as file:
            json.dump(run_info, file, ensure_ascii=True, allow_nan=False, indent=2)
            file.write("\n")
        (directory / "frames").mkdir()
        (directory / "logs").mkdir()

    def save_snapshot(self, state_round: int, rows: tuple[str, ...]) -> None:
        if state_round != self.next_snapshot or state_round > 3000:
            raise ValueError("저장할 상태 번호가 순서에 맞지 않습니다")
        if len(rows) != HEIGHT or any(len(row) != WIDTH or
                any(ord(c) < 32 or ord(c) > 126 for c in row) for row in rows):
            raise ValueError("저장할 그림의 형식이 잘못됐습니다")
        data = ("\n".join(rows) + "\n").encode("ascii")
        hash8 = sha256(data).hexdigest()[:8]
        paths = [Path("frames") / f"frame{state_round:04d}.txt"]
        if state_round % 100 == 0:
            paths.append(Path(f"round{state_round:04d}.txt"))
        for relative in paths:
            with (self.directory / relative).open("xb") as file:
                file.write(data)
            if self.on_save is not None:
                self.on_save({"state_round": state_round, "path": relative.as_posix(),
                              "bytes": len(data), "hash8": hash8})
        if state_round % 100 == 0:
            mode = "x" if state_round == 0 else "a"
            with (self.directory / "RoundHash.txt").open(mode, encoding="ascii", newline="\n") as file:
                file.write(f"round{state_round:04d}.txt {hash8}\n")
        self.next_snapshot += 10
