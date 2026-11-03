"""한 실행 폴더의 snapshot, 메타정보, 로그를 함께 검사한다."""

import argparse
import math
from pathlib import Path
import sys

from .formats import (FRAME_ROUNDS, HASH_RE, RUN_ID_RE, SNAPSHOT_ROUNDS,
                      VALID_N, FormatError, event_records, is_int, is_number,
                      load_json, read_grid, read_log, read_round_hash, sha256_hex)


# 특정 이벤트 로그가 정확히 한 번 있는지 확인한다.
def one_record(records, event, status, errors, label):
    found = event_records(records, event, status)
    if len(found) != 1:
        errors.append(f"{label}: {event} {status} 로그는 1개여야 합니다")
        return None
    return found[0]


# 로그 필드가 예상한 값과 같은지 항목별로 비교한다.
def check_fields(fields, expected, errors, label):
    for name, value in expected.items():
        if fields.get(name) != value:
            errors.append(f"{label}: {name} 값이 {value!r}와 다릅니다")


# 로그에 반드시 있어야 하는 필드가 빠지지 않았는지 확인한다.
def require_fields(fields, names, errors, label):
    missing = [name for name in names if name not in fields]
    if missing:
        errors.append(f"{label}: 필수 필드가 없습니다 ({', '.join(missing)})")


# 값이 음수가 아닌 유한한 수인지 확인한다.
def nonnegative_number(value):
    return is_number(value) and value >= 0


# 값이 bool이 아닌 음수 없는 정수인지 확인한다.
def nonnegative_int(value):
    return is_int(value) and value >= 0


# Worker별 최지연 횟수의 키, 정수 범위와 전체 합계를 검사한다.
def validate_slowest_counts(value, n, expected_total, errors, label):
    if not isinstance(value, dict) or set(value) != {str(k) for k in range(n)}:
        errors.append(f"{label}: slowest_counts의 Worker 번호가 잘못됐습니다")
        return None
    if any(not nonnegative_int(count) for count in value.values()):
        errors.append(f"{label}: slowest_counts는 음수가 아닌 정수여야 합니다")
        return None
    if sum(value.values()) != expected_total:
        errors.append(f"{label}: slowest_counts 합계는 {expected_total}이어야 합니다")
        return None
    return value


# 100회 단위 요약 30개의 범위와 순서가 맞는지 확인한다.
def check_summary_ranges(records, event, errors, label, k=None):
    found = event_records(records, event, "INFO")
    if k is not None:
        found = [record for record in found if record["fields"].get("k") == k]
    if len(found) != 30:
        errors.append(f"{label}: {event} 100회 요약은 30개여야 합니다")
        return
    actual = []
    for record in found:
        fields = record["fields"]
        if any(not is_int(fields.get(name)) for name in ("r_start", "r_end", "count")):
            errors.append(f"{label}: {event} 범위와 횟수는 정수여야 합니다")
            return
        actual.append((fields.get("r_start"), fields.get("r_end"), fields.get("count")))
    expected = [(start, start + 99, 100) for start in range(0, 3000, 100)]
    if actual != expected:
        errors.append(f"{label}: {event} 요약 범위나 순서가 잘못됐습니다")


# run_info.json의 실행 조건과 입력 canvas 해시 형식을 검사한다.
def validate_run_info(run_dir, errors):
    try:
        info = load_json(run_dir / "run_info.json")
    except FormatError as exc:
        errors.append(str(exc))
        return None

    checked = dict(info)
    if info.get("schema_version") != 1:
        errors.append("run_info.json: schema_version은 1이어야 합니다")
    run_id = info.get("run_id")
    if not isinstance(run_id, str) or RUN_ID_RE.fullmatch(run_id) is None:
        errors.append("run_info.json: run_id 형식이 잘못됐습니다")
        checked["run_id"] = None
    team = info.get("team")
    if not is_int(team) or team <= 0:
        errors.append("run_info.json: team은 양의 정수여야 합니다")
        checked["team"] = None
    n = info.get("n")
    if not is_int(n) or n not in VALID_N:
        errors.append("run_info.json: n은 1 또는 4~8이어야 합니다")
        checked["n"] = None
    n_mode = info.get("n_mode")
    if n_mode not in ("fixed", "random") or n == 1 and n_mode != "fixed":
        errors.append("run_info.json: n_mode가 n과 맞지 않습니다")
        checked["n_mode"] = None
    check_fields(info, {"rounds": 3000, "width": 160, "height": 80,
                        "timezone": "KST"}, errors, "run_info.json")

    hashes = info.get("canvas_sha256")
    expected_names = {f"canvas{i}.txt" for i in range(3)}
    if not isinstance(hashes, dict) or set(hashes) != expected_names:
        errors.append("run_info.json: canvas_sha256은 canvas0~2를 모두 가져야 합니다")
        checked["canvas_sha256"] = None
    elif any(not isinstance(value, str) or HASH_RE.fullmatch(value) is None
             for value in hashes.values()):
        errors.append("run_info.json: canvas SHA-256 형식이 잘못됐습니다")
        checked["canvas_sha256"] = None

    timeouts = info.get("timeouts")
    if not isinstance(timeouts, dict) or set(timeouts) != {"startup_s", "io_s"}:
        errors.append("run_info.json: timeouts 형식이 잘못됐습니다")
        checked["timeouts"] = None
    elif any(not is_number(value) or value <= 0 for value in timeouts.values()):
        errors.append("run_info.json: 제한시간은 양의 유한한 수여야 합니다")
        checked["timeouts"] = None
    return checked


# round와 frame의 파일 목록, 형식, 기록 해시를 검사한다.
def validate_snapshots(run_dir, info, errors):
    expected_rounds = {f"round{r:04d}.txt" for r in SNAPSHOT_ROUNDS}
    # Windows의 glob은 대소문자를 구분하지 않아 RoundHash.txt도 잡힐 수 있다.
    actual_rounds = {path.name for path in run_dir.iterdir()
                     if path.is_file() and path.name != "RoundHash.txt"
                     and path.suffix.lower() == ".txt"}
    if actual_rounds != expected_rounds:
        missing = sorted(expected_rounds - actual_rounds)
        extra = sorted(actual_rounds - expected_rounds)
        errors.append(f"round 파일 구성이 잘못됐습니다 (누락={missing}, 추가={extra})")

    frame_dir = run_dir / "frames"
    expected_frames = {f"frame{r:04d}.txt" for r in FRAME_ROUNDS}
    actual_frames = ({path.name for path in frame_dir.iterdir()}
                     if frame_dir.is_dir() else set())
    if actual_frames != expected_frames:
        missing = sorted(expected_frames - actual_frames)
        extra = sorted(actual_frames - expected_frames)
        errors.append(f"frame 파일 구성이 잘못됐습니다 (누락={missing}, 추가={extra})")

    round_data = {}
    frame_data = {}
    for r in SNAPSHOT_ROUNDS:
        path = run_dir / f"round{r:04d}.txt"
        try:
            round_data[r] = read_grid(path)[0]
        except FormatError as exc:
            errors.append(str(exc))
    for r in FRAME_ROUNDS:
        path = frame_dir / f"frame{r:04d}.txt"
        try:
            frame_data[r] = read_grid(path)[0]
        except FormatError as exc:
            errors.append(str(exc))

    try:
        recorded = read_round_hash(run_dir / "RoundHash.txt")
    except FormatError as exc:
        errors.append(str(exc))
        recorded = {}
    for r, data in round_data.items():
        name = f"round{r:04d}.txt"
        actual = sha256_hex(data)[:8]
        if recorded.get(name) != actual:
            errors.append(f"{name}: 기록 해시와 계산 해시가 다릅니다")
        if r in frame_data and frame_data[r] != data:
            errors.append(f"frame{r:04d}.txt가 같은 번호의 round와 다릅니다")
    if info is not None and 0 in round_data:
        hashes = info.get("canvas_sha256")
        if isinstance(hashes, dict) and sha256_hex(round_data[0]) != hashes.get("canvas0.txt"):
            errors.append("round0000.txt가 run_info의 canvas0 해시와 다릅니다")
    return round_data, frame_data, recorded


# 모든 노드 로그에 공통인 run_id와 실패 기록을 검사한다.
def validate_common_log(records, run_id, errors, label):
    for record in records:
        if run_id is not None and record["fields"].get("run_id") != run_id:
            errors.append(f"{label}: {record['line']}번째 로그의 run_id가 다릅니다")
        if record["status"] == "FAIL":
            errors.append(f"{label}: FAIL 로그가 포함되어 있습니다")


# Assigner의 접속, 저장, 통계, 종료 로그를 실행 결과와 대조한다.
def validate_assigner_log(run_dir, info, frame_data, errors):
    path = run_dir / "logs" / "Assigner.txt"
    try:
        records = read_log(path, "ASSIGNER")
    except FormatError as exc:
        errors.append(str(exc))
        return
    run_id = info.get("run_id")
    n, team = info.get("n"), info.get("team")
    if not is_int(n) or n not in VALID_N:
        return
    validate_common_log(records, run_id, errors, "Assigner.txt")

    init = one_record(records, "INIT", "SUCCESS", errors, "Assigner.txt")
    if init:
        expected = {"n": n, "team": team, "bands": [80 * k // n for k in range(n + 1)],
                    "n_mode": info.get("n_mode")}
        check_fields(init["fields"], expected, errors, "Assigner INIT")
        timeouts = info.get("timeouts")
        if isinstance(timeouts, dict):
            check_fields(init["fields"], {"startup_timeout_s": timeouts["startup_s"],
                                          "io_timeout_s": timeouts["io_s"]},
                         errors, "Assigner INIT")
        require_fields(init["fields"], ("host", "port"), errors, "Assigner INIT")
        if not is_int(init["fields"].get("port")) or not 1 <= init["fields"]["port"] <= 65535:
            errors.append("Assigner INIT: port는 1~65535 정수여야 합니다")

    assigns = event_records(records, "ASSIGN", "SUCCESS")
    if len(assigns) != n:
        errors.append("Assigner.txt: ASSIGN 로그 수가 n과 다릅니다")
    else:
        for k, record in enumerate(assigns):
            y0, y1 = 80 * k // n, 80 * (k + 1) // n
            check_fields(record["fields"], {"k": k, "n": n, "y0": y0, "y1": y1,
                                             "h": y1-y0, "team": team},
                         errors, f"Assigner ASSIGN {k}")

    connects = event_records(records, "CONNECT")
    connect_numbers = [record["fields"].get("k") for record in connects]
    if any(not is_int(k) for k in connect_numbers) or sorted(connect_numbers) != list(range(n)):
        errors.append("Assigner.txt: CONNECT의 Worker 번호가 0~N-1과 다릅니다")

    expected_save = {f"frames/frame{r:04d}.txt": r for r in FRAME_ROUNDS}
    expected_save.update({f"round{r:04d}.txt": r for r in SNAPSHOT_ROUNDS})
    saves = event_records(records, "SAVE", "SUCCESS")
    save_paths = [record["fields"].get("path") for record in saves]
    valid_save_paths = [path for path in save_paths if isinstance(path, str)]
    if len(valid_save_paths) != len(save_paths):
        errors.append("Assigner.txt: SAVE path는 문자열이어야 합니다")
    if (len(save_paths) != len(expected_save)
            or len(valid_save_paths) != len(set(valid_save_paths))):
        errors.append("Assigner.txt: SAVE 기록이 누락되거나 중복됐습니다")
    if set(valid_save_paths) != set(expected_save):
        errors.append("Assigner.txt: SAVE 파일 목록이 실제 snapshot 목록과 다릅니다")
    for record in saves:
        fields = record["fields"]
        require_fields(fields, ("state_round", "path", "bytes", "hash8"),
                       errors, "Assigner SAVE")
        path_text = fields.get("path")
        if isinstance(path_text, str):
            expected_round = expected_save.get(path_text)
            if (expected_round is None or not is_int(fields.get("state_round"))
                    or fields.get("state_round") != expected_round):
                errors.append(f"Assigner SAVE: {path_text}의 상태 번호가 잘못됐습니다")
            if expected_round is None:
                continue
            path = run_dir / Path(path_text)
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if not nonnegative_int(fields.get("bytes")) or fields.get("bytes") != len(data) \
                    or fields.get("hash8") != sha256_hex(data)[:8]:
                errors.append(f"Assigner SAVE: {path_text}의 바이트 또는 해시가 다릅니다")

    barriers = event_records(records, "BARRIER", "INFO")
    barrier_times = ("round_avg_ms", "round_max_ms", "wait_avg_ms", "wait_max_ms")
    barrier_totals = {"normal_bytes": 0, "full_bytes": 0,
                      "slowest_counts": {str(k): 0 for k in range(n)}}
    barrier_values_valid = len(barriers) == 30
    for record in barriers:
        fields = record["fields"]
        if any(not nonnegative_number(fields.get(name)) for name in barrier_times):
            errors.append("Assigner BARRIER: 시간은 음수가 아닌 유한한 수여야 합니다")
            barrier_values_valid = False
        elif (fields["round_avg_ms"] > fields["round_max_ms"]
              or fields["wait_avg_ms"] > fields["wait_max_ms"]):
            errors.append("Assigner BARRIER: 평균 시간은 최대 시간보다 클 수 없습니다")
            barrier_values_valid = False
        if (not is_int(fields.get("normal_rounds")) or fields.get("normal_rounds") != 90
                or not is_int(fields.get("full_rounds")) or fields.get("full_rounds") != 10):
            errors.append("Assigner BARRIER: normal/full 횟수는 90/10이어야 합니다")
            barrier_values_valid = False
        for name in ("normal_bytes", "full_bytes"):
            value = fields.get(name)
            if not nonnegative_int(value):
                errors.append(f"Assigner BARRIER: {name}는 음수가 아닌 정수여야 합니다")
                barrier_values_valid = False
            else:
                barrier_totals[name] += value
        counts = validate_slowest_counts(fields.get("slowest_counts"), n, 100,
                                         errors, "Assigner BARRIER")
        if counts is None:
            barrier_values_valid = False
        else:
            for key, value in counts.items():
                barrier_totals["slowest_counts"][key] += value

    check_summary_ranges(records, "ROUND", errors, "Assigner.txt")
    check_summary_ranges(records, "BARRIER", errors, "Assigner.txt")
    for k in range(n):
        check_summary_ranges(records, "RESULT", errors, "Assigner.txt", k)

    repaints = event_records(records, "REPAINT", "INFO")
    if [record["fields"].get("round") for record in repaints] != [1000, 2000]:
        errors.append("Assigner.txt: REPAINT는 1000, 2000 순서여야 합니다")
    elif [(record["fields"].get("canvas"), record["fields"].get("conversion"))
          for record in repaints] != [("canvas1.txt", "brian"),
                                      ("canvas2.txt", "cyclic")]:
        errors.append("Assigner.txt: REPAINT canvas 또는 변환 종류가 잘못됐습니다")
    terminate = one_record(records, "TERMINATE", "SUCCESS", errors, "Assigner.txt")
    if terminate:
        fields = terminate["fields"]
        expected_integers = {"rounds_completed": 3000, "handlers_joined": n,
                             "normal_rounds": 2700, "full_rounds": 300}
        for name, value in expected_integers.items():
            if not is_int(fields.get(name)) or fields.get(name) != value:
                errors.append(f"Assigner TERMINATE: {name} 값은 정수 {value}여야 합니다")
        time_fields = ("elapsed_ms", "throughput_round_s", "round_avg_ms",
                       "round_max_ms", "wait_avg_ms", "wait_max_ms",
                       "normal_avg_bytes", "full_avg_bytes")
        if any(not nonnegative_number(fields.get(name)) for name in time_fields):
            errors.append("Assigner TERMINATE: 시간과 평균은 음수가 아닌 유한한 수여야 합니다")
        elif fields["elapsed_ms"] == 0 or fields["throughput_round_s"] == 0:
            errors.append("Assigner TERMINATE: 총시간과 처리량은 양수여야 합니다")
        elif not math.isclose(fields["throughput_round_s"],
                              3_000_000 / fields["elapsed_ms"], rel_tol=1e-9):
            errors.append("Assigner TERMINATE: 처리량이 총시간과 맞지 않습니다")
        for name in ("normal_bytes", "full_bytes"):
            if not nonnegative_int(fields.get(name)):
                errors.append(f"Assigner TERMINATE: {name}는 음수가 아닌 정수여야 합니다")
        require_fields(fields, ("slowest_counts", "slowest_workers"),
                       errors, "Assigner TERMINATE")
        counts = validate_slowest_counts(fields.get("slowest_counts"), n, 3000,
                                         errors, "Assigner TERMINATE")
        workers = fields.get("slowest_workers")
        if not isinstance(workers, list) or any(not is_int(k) or not 0 <= k < n for k in workers):
            errors.append("Assigner TERMINATE: slowest_workers 형식이 잘못됐습니다")
        elif workers != sorted(set(workers)):
            errors.append("Assigner TERMINATE: slowest_workers는 중복 없는 오름차순이어야 합니다")
        elif counts is not None:
            most = max(counts.values())
            expected_workers = [k for k in range(n) if counts[str(k)] == most]
            if workers != expected_workers:
                errors.append("Assigner TERMINATE: slowest_workers가 slowest_counts와 다릅니다")

        if barrier_values_valid:
            for name in ("normal_bytes", "full_bytes"):
                if fields.get(name) != barrier_totals[name]:
                    errors.append(f"Assigner TERMINATE: {name}가 BARRIER 합계와 다릅니다")
            if counts is not None and counts != barrier_totals["slowest_counts"]:
                errors.append("Assigner TERMINATE: slowest_counts가 BARRIER 합계와 다릅니다")
            round_averages = [record["fields"]["round_avg_ms"] for record in barriers]
            wait_averages = [record["fields"]["wait_avg_ms"] for record in barriers]
            expected_stats = {
                "round_avg_ms": sum(round_averages) / 30,
                "round_max_ms": max(record["fields"]["round_max_ms"] for record in barriers),
                "wait_avg_ms": sum(wait_averages) / 30,
                "wait_max_ms": max(record["fields"]["wait_max_ms"] for record in barriers),
            }
            for name, value in expected_stats.items():
                if not is_number(fields.get(name)) or not math.isclose(fields[name], value,
                                                                       rel_tol=1e-9):
                    errors.append(f"Assigner TERMINATE: {name}가 BARRIER 통계와 다릅니다")
        if (nonnegative_int(fields.get("normal_bytes"))
                and nonnegative_number(fields.get("normal_avg_bytes"))
                and not math.isclose(fields["normal_avg_bytes"],
                                     fields["normal_bytes"] / 2700, rel_tol=1e-9)):
            errors.append("Assigner TERMINATE: normal_avg_bytes 계산이 잘못됐습니다")
        if (nonnegative_int(fields.get("full_bytes"))
                and nonnegative_number(fields.get("full_avg_bytes"))
                and not math.isclose(fields["full_avg_bytes"],
                                     fields["full_bytes"] / 300, rel_tol=1e-9)):
            errors.append("Assigner TERMINATE: full_avg_bytes 계산이 잘못됐습니다")


# Worker 한 개의 할당, 시간, REPAINT, 종료 로그를 검사한다.
def validate_worker_log(run_dir, info, k, errors):
    path = run_dir / "logs" / f"Worker{k}.txt"
    try:
        records = read_log(path, f"WORKER{k}")
    except FormatError as exc:
        errors.append(str(exc))
        return
    run_id = info.get("run_id")
    n, team = info.get("n"), info.get("team")
    validate_common_log(records, run_id, errors, f"Worker{k}.txt")
    init = one_record(records, "INIT", "SUCCESS", errors, f"Worker{k}.txt")
    if init:
        fields = init["fields"]
        timeout_names = ("connect_timeout_s", "startup_timeout_s", "io_timeout_s")
        if any(not is_number(fields.get(name)) or fields[name] <= 0
               for name in timeout_names):
            errors.append(f"Worker{k} INIT: 제한시간은 양수여야 합니다")
        timeouts = info.get("timeouts")
        if isinstance(timeouts, dict):
            check_fields(fields, {"startup_timeout_s": timeouts["startup_s"],
                                  "io_timeout_s": timeouts["io_s"]},
                         errors, f"Worker{k} INIT")
    one_record(records, "CONNECT", "SUCCESS", errors, f"Worker{k}.txt")
    assign = one_record(records, "ASSIGN", "SUCCESS", errors, f"Worker{k}.txt")
    if assign:
        y0, y1 = 80 * k // n, 80 * (k + 1) // n
        check_fields(assign["fields"], {"k": k, "n": n, "y0": y0, "y1": y1,
                                         "h": y1-y0, "team": team},
                     errors, f"Worker{k} ASSIGN")
    check_summary_ranges(records, "ROUND", errors, f"Worker{k}.txt", k)
    for record in event_records(records, "ROUND", "INFO"):
        fields = record["fields"]
        if (not nonnegative_number(fields.get("compute_avg_ms"))
                or not nonnegative_number(fields.get("compute_max_ms"))):
            errors.append(f"Worker{k} ROUND: 계산시간은 음수가 아닌 수여야 합니다")
        elif fields["compute_avg_ms"] > fields["compute_max_ms"]:
            errors.append(f"Worker{k} ROUND: 평균 계산시간이 최대값보다 큽니다")
    repaints = event_records(records, "REPAINT", "INFO")
    if [record["fields"].get("round") for record in repaints] != [1000, 2000]:
        errors.append(f"Worker{k}.txt: REPAINT는 1000, 2000 순서여야 합니다")
    elif [(record["fields"].get("canvas"), record["fields"].get("conversion"))
          for record in repaints] != [("canvas1.txt", "brian"),
                                      ("canvas2.txt", "cyclic")]:
        errors.append(f"Worker{k}.txt: REPAINT canvas 또는 변환 종류가 잘못됐습니다")
    terminate = one_record(records, "TERMINATE", "SUCCESS", errors, f"Worker{k}.txt")
    if terminate:
        check_fields(terminate["fields"], {"k": k, "rounds_completed": 3000},
                     errors, f"Worker{k} TERMINATE")
        if not nonnegative_number(terminate["fields"].get("compute_avg_ms")):
            errors.append(f"Worker{k} TERMINATE: 평균 계산시간은 음수가 아닌 수여야 합니다")


# Assigner와 Worker0~N-1 로그 파일 구성을 모두 검사한다.
def validate_logs(run_dir, info, frame_data, errors):
    if info is None:
        return
    n = info.get("n")
    if not is_int(n) or n not in VALID_N:
        return
    log_dir = run_dir / "logs"
    expected = {"Assigner.txt", *(f"Worker{k}.txt" for k in range(n))}
    actual = {path.name for path in log_dir.glob("*.txt") if path.is_file()} if log_dir.is_dir() else set()
    if actual != expected:
        errors.append(f"로그 파일 구성이 잘못됐습니다 (누락={sorted(expected-actual)}, "
                      f"추가={sorted(actual-expected)})")
    validate_assigner_log(run_dir, info, frame_data, errors)
    for k in range(n):
        validate_worker_log(run_dir, info, k, errors)


# 한 실행 폴더의 메타정보, snapshot, 로그를 순서대로 종합 검사한다.
def verify_run_directory(run_dir):
    run_dir = Path(run_dir)
    errors = []
    if not run_dir.is_dir():
        return None, [f"{run_dir}: 실행 폴더가 없습니다"], {}
    info = validate_run_info(run_dir, errors)
    _, frames, hashes = validate_snapshots(run_dir, info, errors)
    validate_logs(run_dir, info, frames, errors)
    return info, errors, hashes


# 실행 결과 검사에 사용할 실행 폴더 인자를 정의한다.
def parser():
    result = argparse.ArgumentParser(description="HW4 실행 결과 검사")
    result.add_argument("--run-dir", type=Path, required=True)
    return result


# 발견한 오류를 출력하고 검사 성공 여부를 종료 코드로 반환한다.
def main(argv=None):
    args = parser().parse_args(argv)
    _, errors, _ = verify_run_directory(args.run_dir)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"실행 결과 검사 FAIL ({len(errors)}건)", file=sys.stderr)
        return 1
    print("실행 결과 검사 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

