"""canvas 세 장의 수치 조건을 검사한다."""

import argparse
from pathlib import Path
import sys

from .formats import FormatError, read_grid, sha256_hex


# canvas 한 장의 형식, 점 비율, 글자 획과 해시를 검사한다.
def inspect_canvas(path):
    data, rows = read_grid(path)
    text = "".join(rows)
    dots = text.count(".")
    spaces = text.count(" ")
    ink = len(text) - dots - spaces
    ratio = 100.0 * dots / (dots + spaces) if dots + spaces else 0.0
    errors = []
    if not 4.0 <= ratio <= 6.0:
        errors.append(f"점 비율이 4~6%가 아닙니다 ({ratio:.2f}%)")
    if ink < 384:
        errors.append(f"글자 획이 384칸보다 적습니다 ({ink}칸)")
    return {"path": Path(path), "data": data, "sha256": sha256_hex(data),
            "dot_ratio": ratio, "ink": ink, "errors": errors}


# 폴더의 canvas0~2를 검사하고 세 그림이 서로 다른지도 확인한다.
def check_directory(directory):
    directory = Path(directory)
    results = []
    errors = []
    for index in range(3):
        path = directory / f"canvas{index}.txt"
        try:
            result = inspect_canvas(path)
            results.append(result)
            errors.extend(f"{path.name}: {message}" for message in result["errors"])
        except FormatError as exc:
            errors.append(str(exc))
    if len(results) == 3 and len({result["data"] for result in results}) != 3:
        errors.append("canvas 세 장은 서로 다른 그림이어야 합니다")
    return results, errors


# canvas 검사 명령행 인자를 정의한다.
def parser():
    result = argparse.ArgumentParser(description="HW4 canvas 형식 검사")
    result.add_argument("--canvas-dir", type=Path, required=True)
    return result


# 검사 결과를 출력하고 성공 여부를 종료 코드로 반환한다.
def main(argv=None):
    args = parser().parse_args(argv)
    results, errors = check_directory(args.canvas_dir)
    for result in results:
        print(f"{result['path'].name}: 점 {result['dot_ratio']:.2f}%, "
              f"글자 획 {result['ink']}칸, SHA-256 {result['sha256']}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("canvas 검사 PASS (문구와 배치는 별도로 눈으로 확인해야 합니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

