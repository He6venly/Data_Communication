import argparse
import hashlib
from pathlib import Path
import sys

from .board import Board, HEIGHT, WIDTH, ROUNDS


def read_canvas(path):
    # 공백이랑 줄바꿈은 그대로 두고 80×160 ASCII 형식이 맞는지 확인함
    data = Path(path).read_bytes()
    rows = data.split(b"\n")
    if (len(rows) != HEIGHT + 1 or rows[-1] != b""
            or any(len(row) != WIDTH or any(c < 32 or c > 126 for c in row) for row in rows[:-1])):
        raise ValueError(f"canvas 형식이 잘못됐습니다: {path}")
    return [row.decode("ascii") for row in rows[:-1]]


def run(team, canvas_dir, out_dir):
    # 통신 없이 전체 판을 계산해서 결과를 비교할 해시 31개를 만들어줌
    if team <= 0:
        raise ValueError("team은 양의 정수여야 합니다")
    canvases = [read_canvas(Path(canvas_dir) / f"canvas{i}.txt") for i in range(3)]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()):
        raise ValueError("출력 폴더는 비어 있어야 합니다")
    extended = [[c[-1]] + c + [c[0]] for c in canvases[1:]]
    board = Board(canvases[0], *extended, 0, team)
    hashes = []
    with (out_dir / "ReferenceHash.txt").open("x", encoding="ascii", newline="\n") as report:
        for state in range(ROUNDS + 1):
            if state % 100 == 0:
                name = f"round{state:04d}.txt"
                data = ("\n".join(board.rows()) + "\n").encode("ascii")
                with (out_dir / name).open("xb") as output:
                    output.write(data)
                entry = f"{name} {hashlib.sha256(data).hexdigest()[:8]}"
                report.write(entry + "\n")
                report.flush()
                hashes.append(entry)
            if state < ROUNDS:
                board.step(state, board.cur[-2][:], board.cur[1][:])
    return hashes


def main(argv=None):
    parser = argparse.ArgumentParser(description="통신 없는 Worker 기준 계산")
    parser.add_argument("--team", type=int, required=True)
    parser.add_argument("--canvas-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.team <= 0:
        parser.error("team은 양의 정수여야 합니다")
    try:
        hashes = run(args.team, args.canvas_dir, args.out_dir)
        print(f"Reference 완료: {len(hashes)}개 저장")
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as exc:
        print(f"Reference 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
