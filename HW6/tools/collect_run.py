"""공식 verify와 추가 검사를 거친 실행 기록만 별도 폴더에 보관한다."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.check_run import validate


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        """잘못된 수집 옵션은 종료 코드 1로 알린다."""
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def main(argv: list[str] | None = None) -> int:
    """공식 verify와 추가 검사를 통과한 기록 파일만 새 Run 폴더에 보관한다."""
    parser = _Parser(description=__doc__)
    parser.add_argument("--env", required=True)
    parser.add_argument("--kit", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--runs-dir", default="runs")
    args = parser.parse_args(argv)
    cwd = Path.cwd().resolve()
    env_path = Path(args.env).resolve()
    kit = Path(args.kit).resolve()
    runs_dir = Path(args.runs_dir).resolve()
    try:
        env = json.loads(env_path.read_text(encoding="utf-8"))
        if args.run_name not in {"DEV", "A", "B", "C1", "C2", "C3_random", "C3_rarest"}:
            raise ValueError("허용되지 않은 Run 이름")
        if env.get("name") != args.run_name.split("_")[0]:
            raise ValueError("Run 이름이 env.name과 다름")
        if not (kit / "tools" / "verify.py").is_file():
            raise ValueError("KIT/tools/verify.py가 없음")
        if not (cwd / "report.json").is_file() or not (cwd / "logs" / "tracker.jsonl").is_file():
            raise ValueError("VM logs/tracker.jsonl 또는 report.json이 없음")
        if (runs_dir / args.run_name).exists():
            raise FileExistsError(f"이미 결과가 있음: {runs_dir / args.run_name}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"수집 준비 실패: {exc}", file=sys.stderr)
        return 1

    # 큰 실행 데이터는 이동하지 않고 공식 검사 출력을 그대로 기록한다.
    verify = subprocess.run(
        [sys.executable, str(kit / "tools" / "verify.py"), "--env", str(env_path)],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = verify.stdout or ""
    (cwd / "verify.txt").write_text(output, encoding="utf-8")
    print(output, end="" if output.endswith("\n") else "\n")
    if verify.returncode != 0 or "RESULT: PASS" not in output:
        return 1

    # 임시 폴더에서 검사를 마친 뒤 마지막에 이름을 바꿔 부분 결과를 숨긴다.
    runs_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{args.run_name}-", dir=runs_dir))
    try:
        shutil.copytree(cwd / "logs", staging / "logs")
        shutil.copy2(cwd / "report.json", staging / "report.json")
        shutil.copy2(cwd / "verify.txt", staging / "verify.txt")
        for peer in env["peers"]:
            src = cwd / str(peer["dir"])
            dst = staging / str(peer["dir"]).lower()
            dst.mkdir()
            for spec in env["files"]:
                for suffix in (".bitmap", ".lost"):
                    candidate = src / f"{spec['name']}{suffix}"
                    if candidate.is_file():
                        shutil.copy2(candidate, dst / candidate.name)
        run_policy = args.run_name.rsplit("_", 1)[1] if args.run_name.startswith("C3_") else None
        issues = validate(env, staging, run_policy)
        if issues:
            (cwd / "verify.txt").write_text(output + "\n" + "\n".join(f"EXTRA FAIL {item}" for item in issues) + "\n", encoding="utf-8")
            print("추가 검사 실패:\n" + "\n".join(issues), file=sys.stderr)
            return 1
        target = runs_dir / args.run_name
        staging.rename(target)
        print(f"기록 보관 완료: {target}")
        return 0
    except OSError as exc:
        print(f"결과 보관 실패: {exc}", file=sys.stderr)
        return 1
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    raise SystemExit(main())
