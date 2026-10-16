"""Check a single run's twelve logs; a PASS is not proof of remote deployment."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re


TASK_COUNT, EXPECTED_SUM = 1000, 5761455
LINE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\] ([^|]+) \| ([A-Z_]+) \| (SUCCESS|FAIL|INFO|WARN) \| (.+)$")
FILES = ["Coordinator.txt", *[f"Worker{i}.txt" for i in range(1, 11)], "Launcher.txt"]


class LogError(ValueError):
    pass


def read_records(path):
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        match = LINE.fullmatch(line)
        if match is None:
            raise LogError(f"{path.name}:{number}: invalid log envelope")
        node, kind, status, raw = match.groups()
        try:
            fields = json.loads(raw)
        except json.JSONDecodeError as error:
            raise LogError(f"{path.name}:{number}: invalid JSON") from error
        if not isinstance(fields, dict) or not isinstance(fields.get("run_id"), str) or not fields["run_id"]:
            raise LogError(f"{path.name}:{number}: missing run_id")
        if type(fields.get("ts_unix_ms")) is not int:
            raise LogError(f"{path.name}:{number}: missing integer ts_unix_ms")
        if any(key in fields and fields[key] != value
               for key, value in (("event", kind), ("status", status), ("node", node.strip()))):
            raise LogError(f"{path.name}:{number}: JSON disagrees with log envelope")
        records.append({**fields, "event": kind, "status": status, "node": node.strip()})
    if not records:
        raise LogError(f"{path.name}: empty log")
    return records


def verify(log_dir, run_id=None, *, allow_no_crashes=False):
    try:
        return _verify(log_dir, run_id, allow_no_crashes=allow_no_crashes)
    except (KeyError, TypeError, ValueError) as error:
        return {"pass": False, "errors": [f"invalid event data: {error}"], "deployment_verified": False}


def _verify(log_dir, run_id=None, *, allow_no_crashes=False):
    errors, logs = [], {}
    for name in FILES:
        try:
            logs[name] = read_records(Path(log_dir) / name)
        except (OSError, ValueError) as error:
            errors.append(str(error))
    if len(logs) != 12:
        return {"pass": False, "errors": errors, "deployment_verified": False}
    records = [r for rows in logs.values() for r in rows]
    run_ids = {r["run_id"] for r in records}
    if len(run_ids) != 1 or (run_id is not None and run_ids != {run_id}):
        errors.append("logs do not belong to one requested run_id")
    for name, rows in logs.items():
        expected_node = ("COORD" if name == "Coordinator.txt" else
                         "LAUNCHER" if name == "Launcher.txt" else name[:-4].upper())
        if any(r["node"].upper().replace("COORDINATOR", "COORD") != expected_node for r in rows):
            errors.append(f"{name}: unexpected node identity")
        if sum(r["event"] == "INIT" for r in rows) != 1:
            errors.append(f"{name}: expected exactly one INIT (possible appended runs)")
        terminal = [r for r in rows if r["event"] == "TERMINATE"]
        if len(terminal) != 1 or terminal[0]["status"] != "SUCCESS":
            errors.append(f"{name}: missing successful termination")
        if name != "Launcher.txt" and terminal and terminal[-1].get("threads_alive") != 0:
            errors.append(f"{name}: unverified thread shutdown")
        if any(r["event"] == "ERROR" or r["status"] == "FAIL" for r in rows):
            errors.append(f"{name}: failure record present")

    coord = logs["Coordinator.txt"]
    if any(type(r.get("seq")) is not int for r in coord):
        errors.append("Coordinator: missing decision sequence")
        return {"pass": False, "errors": errors, "deployment_verified": False}
    if len({r["seq"] for r in coord}) != len(coord):
        errors.append("Coordinator: duplicate decision sequence")
    coord = sorted(coord, key=lambda r: r["seq"])
    init = next((r for r in coord if r["event"] == "INIT"), {})
    if init.get("dispatchers") != 6 or init.get("task_locks") != 1000 or init.get("workers") != 10:
        errors.append("Coordinator INIT does not confirm the required thread/lock configuration")
    commits = [r for r in coord if r["event"] == "COMMIT"]
    starts = [r for r in coord if r["event"] == "START"]
    final = [r for r in coord if r["event"] == "VERIFY"]
    if len(starts) != 1 or starts[0].get("ring_ready") != 10:
        errors.append("Coordinator: missing ten-worker START")
    else:
        for event in ("HELLO", "RING_OK"):
            if {r.get("worker") for r in coord if r["event"] == event and r["seq"] < starts[0]["seq"]} != set(range(1, 11)):
                errors.append(f"Coordinator: START before ten {event} records")
    if len(commits) != TASK_COUNT or Counter(r.get("task") for r in commits) != Counter(range(TASK_COUNT)):
        errors.append("expected exactly one COMMIT for each of 1000 tasks")
    valid_values = all(type(r.get("result")) is int and r["result"] >= 0 for r in commits)
    total = sum(r["result"] for r in commits) if valid_values else None
    if total != EXPECTED_SUM:
        errors.append("COMMIT result sum is not 5761455")
    if any(r.get("commit_count") != 1 for r in commits):
        errors.append("invalid commit_count")
    if (len(final) != 1 or not final[0].get("pass") or final[0].get("done") != TASK_COUNT
            or final[0].get("commits") != TASK_COUNT or final[0].get("double_commit") != 0
            or final[0].get("sum") != EXPECTED_SUM or not final[0].get("all_commit_once")):
        errors.append("Coordinator VERIFY does not confirm the required invariants")

    owners, epochs, finished = {}, {}, set()
    states = {i: "ALIVE" for i in range(1, 11)}
    targets = {}
    scans, last_death = {}, {}
    cycles = {i: 0 for i in range(1, 11)}
    deaths, rejoins, moves = [], [], []
    for r in coord:
        kind = r["event"]
        if kind == "ASSIGN":
            k, e, worker = r.get("task"), r.get("epoch"), r.get("worker")
            if type(k) is not int or not 0 <= k < TASK_COUNT or k in owners or e != 1 or worker not in range(1, 11):
                errors.append("invalid initial assignment history")
            if states.get(worker) == "DEAD" or r.get("rejoin_count") != cycles.get(worker):
                errors.append("ASSIGN before approved REJOIN or with wrong rejoin cycle")
            owners[k], epochs[k] = worker, e
        elif kind == "TAKEOVER":
            k = r.get("task")
            if (k not in owners or k in finished or owners.get(k) != r.get("from_worker")
                    or epochs.get(k) != r.get("old_epoch") or r.get("epoch") != epochs.get(k, -2)+1
                    or r.get("to_worker") not in range(1, 11)):
                errors.append("invalid takeover ownership/epoch history")
            if targets.get((r.get("from_worker"), r.get("elapsed_ms"))) != r.get("to_worker"):
                errors.append("TAKEOVER does not match the DEAD target")
            if r.get("from_worker") not in scans:
                errors.append("TAKEOVER outside its DEAD ownership scan")
            owners[k], epochs[k] = r.get("to_worker"), r.get("epoch")
            moves.append(r)
        elif kind == "COMMIT":
            k = r.get("task")
            if k in finished or owners.get(k) != r.get("worker") or epochs.get(k) != r.get("epoch"):
                errors.append("COMMIT does not match current epoch/owner")
            finished.add(k)
        elif kind == "DEAD_SCAN":
            source = r.get("worker")
            dead = scans.pop(source, None)
            if (dead is None or r.get("crash_count") != dead.get("crash_count")
                    or r.get("owned_tasks") != dead.get("owned_tasks")
                    or r.get("elapsed_ms") != dead.get("elapsed_ms")):
                errors.append("invalid DEAD scan completion")
            if any(owner == source and k not in finished for k, owner in owners.items()):
                errors.append("DEAD ownership scan omitted an unfinished task")
        elif kind == "DEAD":
            deaths.append(r)
            source = r["worker"]
            previous = last_death.get(source)
            if source in scans or (previous is not None and cycles.get(source) != previous.get("crash_count")):
                errors.append("repeated DEAD without approved REJOIN")
            scans[source] = last_death[source] = r
            dead_now = r.get("dead_now", [])
            if len(dead_now) > 2 or r.get("worker") not in dead_now:
                errors.append("Coordinator concurrent DEAD exceeds two")
            for worker in dead_now:
                states[worker] = "DEAD"
            order = [(source+offset-1) % 10+1 for offset in range(1, 10)]
            target = next((i for state in ("ALIVE", "SUSPECT") for i in order if states.get(i) == state), None)
            targets[(source, r.get("elapsed_ms"))] = target
            if target != r.get("to_worker"):
                errors.append("DEAD target is not the next ALIVE (or fallback SUSPECT)")
            delay = r["elapsed_ms"]-r["last_hb_elapsed_ms"]
            if not math.isfinite(delay) or delay < 5000-0.001:
                errors.append("DEAD was declared before the heartbeat timeout")
            if not math.isclose(delay, r.get("detection_delay_ms", -1), abs_tol=0.001):
                errors.append("DEAD delay disagrees with its monotonic timestamps")
        elif kind == "REJOIN":
            rejoins.append(r)
            worker = r["worker"]
            dead = last_death.get(worker)
            if (states.get(worker) != "DEAD" or worker in scans or dead is None
                    or r.get("rejoin_count") != dead.get("crash_count")
                    or r["seq"] <= dead["seq"]):
                errors.append("approved REJOIN without its completed DEAD cycle")
            cycles[worker] = r.get("rejoin_count")
            states[r["worker"]] = "ALIVE"
        elif kind == "NO_TASK":
            if states.get(r.get("worker")) == "DEAD" or r.get("rejoin_count") != cycles.get(r.get("worker")):
                errors.append("NO_TASK before approved REJOIN or with wrong rejoin cycle")
        elif kind in {"SUSPECT", "ALIVE"}:
            states[r["worker"]] = kind
    if scans:
        errors.append("missing DEAD ownership scan completion")
    if any(type(r.get("elapsed_ms")) not in (int, float) for r in commits+deaths+rejoins+moves):
        errors.append("missing Coordinator decision time")
        return {"pass": False, "errors": errors, "deployment_verified": False}

    launcher = logs["Launcher.txt"]
    down, exited = {}, set()
    crashes = []
    restarts, rejoined = [], []
    ready = set()
    for r in launcher:
        kind, worker = r["event"], r.get("worker")
        if kind == "READY":
            ready.add(worker)
        elif kind == "CRASH":
            if ready != set(range(1, 11)) or worker in down or worker in exited:
                errors.append("CRASH before READY or against a non-running worker")
            down[worker] = "CRASHED"
            crashes.append(r)
        elif kind == "RESTART":
            restarts.append(r)
            if down.get(worker) != "CRASHED":
                errors.append("RESTART without CRASH")
            down[worker] = "REJOINING"
        elif kind == "REJOINED":
            rejoined.append(r)
            if down.get(worker) != "REJOINING":
                errors.append("REJOINED without RESTART")
            down.pop(worker, None)
        elif kind == "EOF":
            down.pop(worker, None)
            exited.add(worker)
        if len(down) > 2:
            errors.append("Launcher concurrent CRASHED+REJOINING exceeds two")
        if kind in {"CRASH", "RESTART", "REJOINED", "EOF"} and set(r.get("down", [])) != set(down):
            errors.append("Launcher down list disagrees with state history")
    if ready != set(range(1, 11)) or exited != set(range(1, 11)):
        errors.append("Launcher must record ten READY and ten EOF events")
    if not crashes and not allow_no_crashes:
        errors.append("no CRASH evidence; use --allow-no-crashes only for development")
    if not (Counter(r.get("worker") for r in crashes) == Counter(r.get("worker") for r in deaths)
            == Counter(r.get("worker") for r in rejoins) == Counter(r.get("worker") for r in restarts)
            == Counter(r.get("worker") for r in rejoined)):
        errors.append("per-worker CRASH, DEAD and approved REJOIN counts differ")
    for events, field in ((crashes, "crash_count"), (deaths, "crash_count"), (rejoins, "rejoin_count")):
        for worker in range(1, 11):
            cycles = [r.get(field) for r in events if r.get("worker") == worker]
            if cycles != list(range(1, len(cycles)+1)):
                errors.append("invalid or duplicated per-worker crash/rejoin cycle")

    by_commit = {r.get("task"): r for r in commits}
    resumes = {}
    sent_results = set()
    for i in range(1, 11):
        for r in logs[f"Worker{i}.txt"]:
            if r["event"] == "RESULT":
                sent_results.add((r.get("task"), r.get("epoch"), i, r.get("result")))
            if r["event"] == "TAKEOVER":
                key = (r.get("task"), r.get("epoch"), i)
                step = r.get("resume_step")
                if key in resumes or type(step) is not int or not 1 <= step <= 10:
                    errors.append("invalid/duplicate Worker TAKEOVER resume record")
                resumes[key] = r
    if any((r.get("task"), r.get("epoch"), r.get("worker"), r.get("result")) not in sent_results for r in commits):
        errors.append("Coordinator COMMIT has no matching Worker RESULT record")
    fault_metrics = []
    for dead in deaths:
        worker, cycle = dead["worker"], dead["crash_count"]
        owned = dead.get("owned_tasks", [])
        related = [r for r in moves if r["from_worker"] == worker and r["elapsed_ms"] == dead["elapsed_ms"]]
        if Counter(r["task"] for r in related) != Counter(owned):
            errors.append("DEAD owned tasks and TAKEOVER records differ")
        saved = sum(resumes.get((r["task"], r["epoch"], r["to_worker"]), {}).get("resume_step", 1)-1
                    for r in related)
        recovery = (max(by_commit[k]["elapsed_ms"] for k in owned)-dead["elapsed_ms"]
                    if owned and all(k in by_commit for k in owned) else None)
        rejoin = next((r for r in rejoins if r["worker"] == worker and r.get("rejoin_count") == cycle), None)
        assign = next((r for r in coord if r["event"] == "ASSIGN" and r["worker"] == worker
                       and r.get("rejoin_count") == cycle and rejoin is not None
                       and r["seq"] > rejoin["seq"]), None)
        no_task = any(r["event"] == "NO_TASK" and r.get("worker") == worker
                      and r.get("rejoin_count") == cycle and rejoin is not None
                      and r["seq"] > rejoin["seq"] for r in coord)
        if rejoin is not None and assign is None and not no_task:
            errors.append("rejoined Worker has neither new ASSIGN nor NO_TASK evidence")
        fault_metrics.append({"worker": worker, "crash_count": cycle,
                              "owned_tasks": owned, "to_worker": dead["to_worker"],
                              "last_hb_elapsed_ms": dead["last_hb_elapsed_ms"],
                              "dead_elapsed_ms": dead["elapsed_ms"],
                              "detection_ms": dead["elapsed_ms"]-dead["last_hb_elapsed_ms"], "recovery_ms": recovery,
                              "rejoin_latency_ms": None if assign is None or rejoin is None else
                              assign["elapsed_ms"]-rejoin["elapsed_ms"],
                              "first_task": None if assign is None else assign["task"],
                              "post_rejoin_commits": sum(r.get("worker") == worker and r.get("rejoin_count") == cycle
                                                         for r in commits),
                              "ckpt_saving": saved/(len(related)*10) if related else None})
    execution_ms = max((r["elapsed_ms"] for r in commits), default=0)
    return {"pass": not errors, "run_id": next(iter(run_ids)) if len(run_ids) == 1 else None,
            "tasks": len(finished), "commits": len(commits), "sum": total,
            "crashes": len(crashes), "execution_ms": execution_ms,
            "throughput": len(commits)*1000/execution_ms if execution_ms else None,
            "faults": fault_metrics, "errors": sorted(set(errors)), "deployment_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="동일 실행 로그 12개의 정합성·복구 지표 검사")
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--allow-no-crashes", action="store_true", help="개발용 무장애 실행에만 사용")
    parser.add_argument("--output", type=Path, help="분석 결과 JSON 저장 위치")
    args = parser.parse_args(argv)
    try:
        report = verify(args.log_dir, args.run_id, allow_no_crashes=args.allow_no_crashes)
    except (KeyError, TypeError, ValueError) as error:
        report = {"pass": False, "errors": [f"invalid event data: {error}"], "deployment_verified": False}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text+"\n", encoding="utf-8")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
