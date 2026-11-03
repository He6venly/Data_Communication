"""기준 실행과 분산 실행 두 개의 RoundHash를 비교한다."""

import argparse
from pathlib import Path
import sys

from .formats import SNAPSHOT_ROUNDS
from .verify_run import verify_run_directory


def validate_runs(team, baseline, run_a, run_b):
    named = (("baseline", Path(baseline)), ("run-a", Path(run_a)),
             ("run-b", Path(run_b)))
    runs = []
    errors = []
    for label, path in named:
        info, run_errors, hashes = verify_run_directory(path)
        errors.extend(f"{label}: {error}" for error in run_errors)
        runs.append((label, path, info, hashes))
    if errors:
        return runs, errors

    infos = [item[2] for item in runs]
    if infos[0]["n"] != 1 or infos[0]["n_mode"] != "fixed":
        errors.append("baseline은 fixed N=1 실행이어야 합니다")
    distributed_n = [infos[1]["n"], infos[2]["n"]]
    if any(n not in (4, 5, 6, 7, 8) for n in distributed_n):
        errors.append("run-a와 run-b의 N은 4~8이어야 합니다")
    if distributed_n[0] == distributed_n[1]:
        errors.append("run-a와 run-b의 N은 서로 달라야 합니다")
    if infos[1]["n_mode"] != "random" or infos[2]["n_mode"] != "random":
        errors.append("run-a와 run-b는 random N 실행이어야 합니다")
    if any(info["team"] != team for info in infos):
        errors.append("세 실행의 team이 요청한 조 번호와 다릅니다")
    if len({tuple(sorted(info["canvas_sha256"].items())) for info in infos}) != 1:
        errors.append("세 실행에 기록된 canvas SHA-256이 다릅니다")
    return runs, errors


def make_result(team, baseline, run_a, run_b, output):
    runs, errors = validate_runs(team, baseline, run_a, run_b)
    if errors:
        return errors, False
    infos = [item[2] for item in runs]
    hash_columns = [item[3] for item in runs]
    ns = [info["n"] for info in infos]
    lines = [f"TEAM {team}", f"ROUND N={ns[0]} N={ns[1]} N={ns[2]} RESULT"]
    same_count = 0
    for r in SNAPSHOT_ROUNDS:
        name = f"round{r:04d}.txt"
        values = [column[name] for column in hash_columns]
        same = len(set(values)) == 1
        same_count += same
        lines.append(f"{r:04d} {' '.join(values)} {'SAME' if same else 'DIFF'}")
    final = [column["round3000.txt"] for column in hash_columns]
    final_same = len(set(final)) == 1
    lines.append(f"FINAL {' '.join(final)} {'SAME' if final_same else 'DIFF'}")
    passed = same_count == 31 and final_same
    lines.append(f"TOTAL {same_count}/31 SAME -> {'PASS' if passed else 'FAIL'}")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="ascii", newline="\n") as file:
        file.write("\n".join(lines) + "\n")
    return [], passed


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("양의 정수가 필요합니다")
    return number


def parser():
    result = argparse.ArgumentParser(description="HW4 세 실행 해시 비교")
    result.add_argument("--team", type=positive_int, required=True)
    result.add_argument("--baseline", type=Path, required=True)
    result.add_argument("--run-a", type=Path, required=True)
    result.add_argument("--run-b", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        errors, passed = make_result(args.team, args.baseline, args.run_a,
                                     args.run_b, args.output)
    except OSError as exc:
        print(f"hash_result 생성 실패: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"{args.output}: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

