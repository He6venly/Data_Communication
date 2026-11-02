"""작업 분배 서버의 실행 인자와 전체 실행 흐름을 연결한다."""

import argparse
import math
from pathlib import Path
import re
import sys

from .barrier import run_rounds
from .log import AssignerLog
from .metrics import Metrics
from .partition import bands, choose_worker_count
from .server import accept_workers
from .storage import RunStorage, read_canvases
from .transport import PhaseTimeout


def positive_int(value: str) -> int:
    try:
        number = int(value)
        if number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("양의 정수가 필요합니다")


def positive_float(value: str) -> float:
    try:
        number = float(value)
        if math.isfinite(number) and number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("양의 유한한 수가 필요합니다")


def run_id_type(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value, flags=re.ASCII):
        return value
    raise argparse.ArgumentTypeError("실행 식별자 형식이 잘못됐습니다")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="작업 분배 서버")
    result.add_argument("--host", required=True)
    result.add_argument("--port", type=int, required=True, choices=range(1, 65536), metavar="PORT")
    result.add_argument("--team", type=positive_int, required=True)
    result.add_argument("--canvas-dir", type=Path, required=True)
    result.add_argument("--out-dir", type=Path, required=True)
    result.add_argument("--run-id", type=run_id_type, required=True)
    result.add_argument("--n", type=int, choices=(1, 4, 5, 6, 7, 8))
    result.add_argument("--startup-timeout", type=positive_float, default=300.0)
    result.add_argument("--io-timeout", type=positive_float, default=120.0)
    return result


def execute(args: argparse.Namespace) -> int:
    log = None
    metrics = None
    connections = []

    def log_failure(exc, reason):
        if log is None:
            return
        fields = {"reason": reason,
                  "rounds_completed": getattr(exc, "rounds_completed", len(metrics.measurements) if metrics else 0),
                  "handlers_joined": getattr(exc, "handlers_joined", 0)}
        if isinstance(exc, PhaseTimeout):
            fields.update(reason="timeout", phase=exc.phase, timeout_s=exc.timeout_s)
        for name in ("round", "k"):
            if hasattr(exc, name):
                fields[name] = getattr(exc, name)
        try:
            log.write("TERMINATE", "FAIL", **fields)
        except OSError as log_error:
            print(f"실패 로그 기록 오류: {log_error}", file=sys.stderr)

    try:
        canvases = read_canvases(args.canvas_dir)
        n, n_mode = choose_worker_count(args.n)
        ranges = bands(n)
        info = {"schema_version": 1, "run_id": args.run_id, "team": args.team,
                "n": n, "n_mode": n_mode, "rounds": 3000, "width": 160,
                "height": 80, "timezone": "KST",
                "canvas_sha256": {f"canvas{i}.txt": canvas.sha256
                                  for i, canvas in enumerate(canvases)},
                "timeouts": {"startup_s": args.startup_timeout, "io_s": args.io_timeout}}
        storage = RunStorage(args.out_dir, info)
        log = AssignerLog(args.out_dir / "logs" / "Assigner.txt", args.run_id)
        storage.on_save = lambda fields: log.write("SAVE", "SUCCESS", **fields)
        metrics = Metrics(n)

        def ready(address):
            line = log.write("INIT", "SUCCESS", n=n, team=args.team,
                             bands=[ranges[0][0]] + [y1 for _, y1 in ranges], n_mode=n_mode,
                             host=args.host, port=address[1], startup_timeout_s=args.startup_timeout,
                             io_timeout_s=args.io_timeout)
            print(line, flush=True)

        def connected(k):
            log.write("CONNECT", "INFO", k=k, n=n)

        def assigned(k, y0, y1):
            log.write("ASSIGN", "SUCCESS", k=k, n=n, y0=y0, y1=y1, h=y1-y0, team=args.team)

        def record(measurement):
            summary = metrics.add(measurement)
            r = measurement.round
            if r in (1000, 2000):
                log.write("REPAINT", "INFO", round=r,
                          canvas="canvas1.txt" if r == 1000 else "canvas2.txt",
                          conversion="brian" if r == 1000 else "cyclic")
            if summary is not None:
                log.write("ROUND", "INFO", r_start=summary["r_start"], r_end=summary["r_end"],
                          count=summary["count"])
                for k in range(n):
                    log.write("RESULT", "INFO", k=k, r_start=summary["r_start"],
                              r_end=summary["r_end"], count=summary["count"])
                log.write("BARRIER", "INFO", **summary)

        # 입력과 출력 준비 후 접속, 계산, 저장 순서로 실행한다.
        connections = accept_workers(args.host, args.port, n, args.team, canvases,
                                     args.startup_timeout, ready, connected, assigned)
        elapsed_ms, joined = run_rounds(connections, canvases[0], args.io_timeout,
                                        storage.save_snapshot, record)
        log.write("TERMINATE", "SUCCESS", **metrics.finish(elapsed_ms, joined))
        return 0
    except KeyboardInterrupt as exc:
        print("실행이 중단됐습니다", file=sys.stderr)
        log_failure(exc, "interrupted")
        return 130
    except Exception as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        log_failure(exc, str(exc))
        return 1
    finally:
        for connection in connections:
            connection.close()
        if log is not None:
            log.close()


def main() -> int:
    return execute(parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
