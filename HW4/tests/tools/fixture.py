"""도구 테스트에서 사용하는 작은 실행 폴더 제작 함수."""

from hashlib import sha256
import json
from pathlib import Path


def grid(character=" "):
    return ((character * 160 + "\n") * 80).encode("ascii")


def log_line(node, event, status, run_id, **fields):
    body = json.dumps({"run_id": run_id, **fields}, ensure_ascii=True,
                      allow_nan=False, separators=(",", ":"))
    return f"[12:34:56.789] {node} | {event} | {status} | {body}\n"


def change_log(path, event, updates, occurrence=0):
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    seen = 0
    for index, line in enumerate(lines):
        parts = line.split(" | ", 3)
        if len(parts) != 4 or parts[1] != event:
            continue
        if seen == occurrence:
            fields = json.loads(parts[3])
            fields.update(updates)
            parts[3] = json.dumps(fields, ensure_ascii=True, separators=(",", ":"))
            lines[index] = " | ".join(parts)
            break
        seen += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def make_run(root, n=1, n_mode="fixed", team=2, later_character=" ", run_id=None):
    root = Path(root)
    root.mkdir(parents=True)
    (root / "frames").mkdir()
    (root / "logs").mkdir()
    run_id = run_id or f"test-n{n}"
    first = grid(" ")
    later = grid(later_character)
    canvas_hash = sha256(first).hexdigest()
    info = {
        "schema_version": 1,
        "run_id": run_id,
        "team": team,
        "n": n,
        "n_mode": n_mode,
        "rounds": 3000,
        "width": 160,
        "height": 80,
        "timezone": "KST",
        "canvas_sha256": {f"canvas{i}.txt": canvas_hash for i in range(3)},
        "timeouts": {"startup_s": 300.0, "io_s": 120.0},
    }
    (root / "run_info.json").write_text(json.dumps(info, indent=2) + "\n",
                                         encoding="utf-8", newline="\n")

    hashes = []
    saved = []
    for state_round in range(0, 3001, 10):
        data = first if state_round == 0 else later
        frame_name = f"frames/frame{state_round:04d}.txt"
        (root / frame_name).write_bytes(data)
        saved.append((state_round, frame_name, data))
        if state_round % 100 == 0:
            round_name = f"round{state_round:04d}.txt"
            (root / round_name).write_bytes(data)
            saved.append((state_round, round_name, data))
            hashes.append(f"{round_name} {sha256(data).hexdigest()[:8]}\n")
    (root / "RoundHash.txt").write_text("".join(hashes), encoding="ascii", newline="\n")

    assigner = []
    block_counts = {str(k): 100//n + (1 if k < 100 % n else 0) for k in range(n)}
    total_counts = {key: value * 30 for key, value in block_counts.items()}
    assigner.append(log_line("ASSIGNER", "INIT", "SUCCESS", run_id, n=n, team=team,
                             bands=[80*k//n for k in range(n+1)], n_mode=n_mode,
                             host="127.0.0.1", port=9000,
                             startup_timeout_s=300.0, io_timeout_s=120.0))
    for k in range(n):
        y0, y1 = 80*k//n, 80*(k+1)//n
        assigner.append(log_line("ASSIGNER", "CONNECT", "INFO", run_id, k=k, n=n))
        assigner.append(log_line("ASSIGNER", "ASSIGN", "SUCCESS", run_id,
                                 k=k, n=n, y0=y0, y1=y1, h=y1-y0, team=team))
    for state_round, path, data in saved:
        assigner.append(log_line("ASSIGNER", "SAVE", "SUCCESS", run_id,
                                 state_round=state_round, path=path, bytes=len(data),
                                 hash8=sha256(data).hexdigest()[:8]))
    for start in range(0, 3000, 100):
        if start in (1000, 2000):
            assigner.append(log_line("ASSIGNER", "REPAINT", "INFO", run_id,
                                     round=start,
                                     canvas=f"canvas{start//1000}.txt",
                                     conversion="brian" if start == 1000 else "cyclic"))
        common = {"r_start": start, "r_end": start+99, "count": 100}
        assigner.append(log_line("ASSIGNER", "ROUND", "INFO", run_id, **common))
        for k in range(n):
            assigner.append(log_line("ASSIGNER", "RESULT", "INFO", run_id, k=k, **common))
        assigner.append(log_line("ASSIGNER", "BARRIER", "INFO", run_id,
                                 **common, round_avg_ms=1.0, round_max_ms=2.0,
                                 wait_avg_ms=0.1, wait_max_ms=0.2,
                                 slowest_counts=block_counts,
                                 normal_rounds=90, full_rounds=10,
                                 normal_bytes=1000, full_bytes=2000))
    most = max(total_counts.values())
    assigner.append(log_line("ASSIGNER", "TERMINATE", "SUCCESS", run_id,
                             rounds_completed=3000, elapsed_ms=3000.0,
                             throughput_round_s=1000.0, handlers_joined=n,
                             round_avg_ms=1.0, round_max_ms=2.0,
                             wait_avg_ms=0.1, wait_max_ms=0.2,
                             slowest_counts=total_counts,
                             slowest_workers=[k for k in range(n)
                                              if total_counts[str(k)] == most],
                             normal_rounds=2700, full_rounds=300,
                             normal_bytes=30000, full_bytes=60000,
                             normal_avg_bytes=30000/2700,
                             full_avg_bytes=60000/300))
    (root / "logs" / "Assigner.txt").write_text("".join(assigner),
                                                   encoding="utf-8", newline="\n")

    for k in range(n):
        y0, y1 = 80*k//n, 80*(k+1)//n
        worker = [
            log_line(f"WORKER{k}", "INIT", "SUCCESS", run_id,
                     connect_timeout_s=10.0, startup_timeout_s=300.0, io_timeout_s=120.0),
            log_line(f"WORKER{k}", "CONNECT", "SUCCESS", run_id,
                     host="127.0.0.1", port=9000),
            log_line(f"WORKER{k}", "ASSIGN", "SUCCESS", run_id,
                     k=k, n=n, y0=y0, y1=y1, h=y1-y0, team=team),
        ]
        for start in range(0, 3000, 100):
            if start in (1000, 2000):
                worker.append(log_line(f"WORKER{k}", "REPAINT", "INFO", run_id,
                                       round=start, canvas=f"canvas{start//1000}.txt",
                                       conversion="brian" if start == 1000 else "cyclic"))
            worker.append(log_line(f"WORKER{k}", "ROUND", "INFO", run_id,
                                   k=k, r_start=start, r_end=start+99, count=100,
                                   compute_avg_ms=1.0, compute_max_ms=2.0))
        worker.append(log_line(f"WORKER{k}", "TERMINATE", "SUCCESS", run_id,
                               k=k, rounds_completed=3000, compute_avg_ms=1.0))
        (root / "logs" / f"Worker{k}.txt").write_text("".join(worker),
                                                       encoding="utf-8", newline="\n")
    return root

