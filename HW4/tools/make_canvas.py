"""재현 가능한 G2 입력 그림 세 장을 만든다."""

import argparse
from pathlib import Path
import random
import sys

from .formats import HEIGHT, WIDTH, sha256_hex, write_grid


# 과제에 필요한 문자를 직접 그린 5x7 글꼴이다. 1은 획, 0은 빈칸을 뜻한다.
FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "11001", "10101", "10011", "10011", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
}

LAYOUTS = (
    (("G{team}", 8, 6), ("CONNECT", 28, 25), ("BUILD TOGETHER", 8, 51)),
    (("G{team}", 112, 8), ("SHARE IDEAS", 12, 32), ("GROW AS ONE", 40, 60)),
    (("G{team}", 65, 5), ("IN SYNC", 10, 22), ("BEYOND LIMITS", 20, 46)),
)
INK = ("#", "@", "+")


def draw_text(board, text, x, y, ink):
    cursor = x
    for character in text:
        if character == " ":
            cursor += 6
            continue
        glyph = FONT.get(character)
        if glyph is None:
            raise ValueError(f"글꼴에 없는 문자입니다: {character}")
        if cursor + 10 > WIDTH or y + 7 > HEIGHT:
            raise ValueError(f"문구가 canvas 범위를 벗어납니다: {text}")
        for dy, pattern in enumerate(glyph):
            for dx, value in enumerate(pattern):
                if value == "1":
                    board[y + dy][cursor + dx * 2] = ink
                    board[y + dy][cursor + dx * 2 + 1] = ink
        cursor += 11


def make_boards(team, seed):
    boards = []
    for index, layout in enumerate(LAYOUTS):
        board = [[" "] * WIDTH for _ in range(HEIGHT)]
        for text, x, y in layout:
            draw_text(board, text.format(team=team), x, y, INK[index])
        rng = random.Random(seed + index)
        for y in range(HEIGHT):
            for x in range(WIDTH):
                if board[y][x] == " " and rng.random() < 0.05:
                    board[y][x] = "."
        boards.append(tuple("".join(row) for row in board))
    return tuple(boards)


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("양의 정수가 필요합니다")
    return number


def parser():
    result = argparse.ArgumentParser(description="HW4 canvas 세 장 생성")
    result.add_argument("--team", type=positive_int, required=True)
    result.add_argument("--seed", type=int, required=True)
    result.add_argument("--out-dir", type=Path, required=True)
    return result


def run(team, seed, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()):
        raise FileExistsError(f"{out_dir}: 출력 폴더가 비어 있지 않습니다")
    hashes = {}
    for index, rows in enumerate(make_boards(team, seed)):
        name = f"canvas{index}.txt"
        data = write_grid(out_dir / name, rows)
        hashes[name] = sha256_hex(data)
    return hashes


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        hashes = run(args.team, args.seed, args.out_dir)
    except (OSError, ValueError) as exc:
        print(f"canvas 생성 실패: {exc}", file=sys.stderr)
        return 1
    for name, digest in hashes.items():
        print(f"{name} {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

