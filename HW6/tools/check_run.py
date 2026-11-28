"""보관된 실행 기록의 형식·지표·결과 파일을 교차 검사한다."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        """검사 CLI의 인자 오류를 종료 코드 1로 통일한다."""
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _lost(bitmap: str) -> str:
    """bitmap의 0 구간을 저장 규칙에 맞는 .lost 문자열로 바꾼다."""
    missing = [idx for idx, bit in enumerate(bitmap) if bit == "0"]
    if not missing:
        return ""
    result: list[str] = []
    start = last = missing[0]
    for idx in missing[1:]:
        if idx != last + 1:
            result.append(str(start) if start == last else f"{start}-{last}")
            start = idx
        last = idx
    result.append(str(start) if start == last else f"{start}-{last}")
    return ",".join(result)


def _events(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """JSONL을 읽어 형식·시각 순서·마지막 EXIT를 검사한다."""
    issues: list[str] = []
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return [], [f"로그 없음: {path}"]
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            issues.append(f"빈 로그 줄: {path}:{number}")
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(f"JSON 오류: {path}:{number}: {exc}")
            continue
        if not isinstance(row, dict):
            issues.append(f"JSON 객체가 아님: {path}:{number}")
            continue
        if not isinstance(row.get("t"), (int, float)) or not math.isfinite(row["t"]):
            issues.append(f"t 필드 오류: {path}:{number}")
        if not isinstance(row.get("peer"), str) or not isinstance(row.get("ev"), str):
            issues.append(f"peer/ev 필드 오류: {path}:{number}")
        rows.append(row)
    times = [row["t"] for row in rows if isinstance(row.get("t"), (int, float))]
    if any(right < left for left, right in zip(times, times[1:])):
        issues.append(f"로그 시각이 역행함: {path}")
    if rows and rows[-1].get("ev") != "EXIT":
        issues.append(f"마지막 이벤트가 EXIT가 아님: {path}")
    return rows, issues


def validate(env: dict[str, Any], run_dir: Path, policy: str | None = None) -> list[str]:
    """다섯 로그, 보고서, 종료 코드, 평균 속도, bitmap/lost를 교차 대조한다."""
    issues: list[str] = []
    expected_victim = (env.get("destroy") or {}).get("peer")
    files = env.get("files", [])
    chunk_size = int(env["chunk_size"])
    chosen_policy = policy or env.get("download", {}).get("policy")
    if chosen_policy not in ("random", "rarest"):
        issues.append("정책을 확정할 수 없음; C3는 --policy가 필요함")

    for peer in env.get("peers", []):
        peer_id = str(peer["id"])
        rows, found = _events(run_dir / "logs" / f"{peer_id}.jsonl")
        issues.extend(found)
        if rows:
            starts = [row for row in rows if row.get("ev") == "START"]
            if not starts or rows[0].get("ev") != "START":
                issues.append(f"{peer_id}: 첫 이벤트 START가 없음")
            elif starts[0].get("policy") != chosen_policy:
                issues.append(f"{peer_id}: START 정책이 {chosen_policy}와 다름")
            exit_rows = [row for row in rows if row.get("ev") == "EXIT"]
            want = 3 if peer_id == expected_victim else 0
            if not exit_rows or exit_rows[-1].get("code") != want:
                issues.append(f"{peer_id}: EXIT code가 {want}가 아님")
            for row in rows:
                ev = row.get("ev")
                required = {
                    "RECV": ("file", "idx", "src"),
                    "HASH": ("file", "ok", "sec"),
                    "CORRUPT": ("file", "action", "tries"),
                    "STALLED": ("file", "lost"),
                    "DONE": ("kind", "detail"),
                    "EXIT": ("code", "up_mb", "down_mb"),
                }.get(ev, ())
                if any(field not in row for field in required):
                    issues.append(f"{peer_id}: {ev} 필수 필드 누락")
            exits = [row for row in rows if row.get("ev") == "EXIT"]
            if exits:
                duration = float(exits[-1].get("t", 0.0))
                if duration <= 0:
                    issues.append(f"{peer_id}: 종료 시각이 0 이하임")
                else:
                    up = float(exits[-1].get("up_mb", 0.0)) * 1024 / duration
                    down = float(exits[-1].get("down_mb", 0.0)) * 1024 / duration
                    if up > int(peer["up_kbps"]) + 1:
                        issues.append(f"{peer_id}: 평균 UP {up:.1f} KB/s가 한도를 넘음")
                    if down > int(peer["down_kbps"]) + 1:
                        issues.append(f"{peer_id}: 평균 DOWN {down:.1f} KB/s가 한도를 넘음")

    tracker, found = _events(run_dir / "logs" / "tracker.jsonl")
    issues.extend(found)
    if tracker and (tracker[0].get("ev") != "START_PROGRAM" or tracker[-1].get("ev") != "EXIT"):
        issues.append("Tracker 로그의 시작/종료 이벤트 위치 오류")
    report_path = run_dir / "report.json"
    if not report_path.is_file():
        issues.append("report.json 없음")
        report: dict[str, Any] = {}
    else:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report = {}
            issues.append(f"report.json 읽기 실패: {exc}")
    report_keys = (
        "env", "run", "seed", "policy", "destroy_plan", "crashes_sent", "T_rep", "p_rep",
        "upstat_at_rep", "dup_ratio", "T_destroy", "p_destroy", "T_dead", "T_done",
        "T_last_done", "T_alldone", "T_exit", "done_kind", "peers", "abort",
    )
    if report and not isinstance(report, dict):
        issues.append("report.json 최상위 값이 객체가 아님")
        report = {}
    if report:
        if any(key not in report for key in report_keys):
            issues.append("report.json 필수 필드 누락")
        if report.get("env") != env.get("name") or report.get("run") != env.get("run"):
            issues.append("report.json의 env/run이 입력 env와 다름")
        if report.get("policy") not in (None, chosen_policy):
            issues.append("report.json 정책이 검사 정책과 다름")

    record_root = run_dir
    bitmaps_by_file: dict[str, dict[str, str]] = {str(spec["name"]): {} for spec in files}
    for peer in env.get("peers", []):
        peer_id = str(peer["id"])
        peer_dir = record_root / str(peer["dir"]).lower()
        for spec in files:
            name = str(spec["name"])
            nchunks = (int(spec["size"]) + chunk_size - 1) // chunk_size
            bitmap_path = peer_dir / f"{name}.bitmap"
            if not bitmap_path.is_file():
                issues.append(f"{peer_id} bitmap 없음: {name}")
                continue
            bitmap = bitmap_path.read_text(encoding="ascii")
            if len(bitmap) != nchunks or set(bitmap) - {"0", "1"}:
                issues.append(f"{peer_id} bitmap 형식 오류: {name}")
                continue
            bitmaps_by_file[name][peer_id] = bitmap
            lost = _lost(bitmap)
            lost_path = peer_dir / f"{name}.lost"
            if lost and (not lost_path.is_file() or lost_path.read_text(encoding="ascii") != lost):
                issues.append(f"{peer_id} lost가 bitmap과 다름: {name}")
            if not lost and lost_path.exists():
                issues.append(f"{peer_id} 완성 bitmap에 .lost가 있음: {name}")
    survivors = [str(peer["id"]) for peer in env.get("peers", []) if str(peer["id"]) != expected_victim]
    for name, by_peer in bitmaps_by_file.items():
        survivor_bits = [by_peer[peer_id] for peer_id in survivors if peer_id in by_peer]
        if len(survivor_bits) != len(survivors) or len(set(survivor_bits)) > 1:
            issues.append(f"생존자 bitmap 수렴 오류: {name}")
    verify_path = run_dir / "verify.txt"
    if not verify_path.is_file() or "RESULT: PASS" not in verify_path.read_text(encoding="utf-8", errors="replace"):
        issues.append("verify.txt에 공식 RESULT: PASS가 없음")
    return issues


def main(argv: list[str] | None = None) -> int:
    """검사 결과를 사람이 읽는 PASS/FAIL 목록으로 출력한다."""
    parser = _Parser(description=__doc__)
    parser.add_argument("--env", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--policy", choices=("random", "rarest"))
    args = parser.parse_args(argv)
    try:
        env = json.loads(Path(args.env).read_text(encoding="utf-8"))
        issues = validate(env, Path(args.run_dir).resolve(), args.policy)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"검사 입력 오류: {exc}", file=sys.stderr)
        return 1
    if issues:
        for issue in issues:
            print(f"FAIL {issue}")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
