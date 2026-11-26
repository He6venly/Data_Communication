"""Tracker CLI·시그널·최종 report와 마지막 EXIT 기록을 담당함."""

from __future__ import annotations

from pathlib import Path
import signal
import sys
import threading
import time

from src.common.contracts import ConfigurationError
from .config import load_env, parse_args
from .log import EventLog
from .report import write_report
from .server import TrackerServer


def main(argv: list[str] | None = None) -> int:
    """입력을 검증하고 서버 정리·report·EXIT 순서로 실행을 마침."""
    started_at = time.monotonic()
    try:
        args = parse_args(argv)
        env = load_env(args.env)
    except ConfigurationError as exc:
        print(f"Tracker 설정 오류: {exc}\n사용법: python -m src.tracker --env ENV [PORT]", file=sys.stderr)
        return 1
    root = Path.cwd()
    log = None
    server = None
    previous = {}
    ready, clean = False, True
    code = 1
    report = None
    try:
        log = EventLog(peer_id="tracker", root=root, started_at=started_at)
        log.event("START_PROGRAM", env=env["name"])
        server = TrackerServer(env=env, emit=log.event, port=args.port)
        if threading.current_thread() is threading.main_thread():
            def stop(signum, frame):
                """시그널 수신 시 종료 요구만 설정하고 정리는 main에 맡김."""
                server.request_stop()
            signals = [signal.SIGINT, signal.SIGTERM]
            if hasattr(signal, "SIGBREAK"):
                signals.append(signal.SIGBREAK)
            for signum in signals:
                previous[signum] = signal.signal(signum, stop)
        server.start()
        ready = True
        print(f"Tracker listening {server.address[0]}:{server.address[1]}", flush=True)
        code = server.wait()
        if server.failure is not None:
            raise server.failure
    except Exception as exc:
        code = 2 if ready else 1
        print(f"Tracker 실행 오류: {exc}", file=sys.stderr)
        if log is not None:
            try:
                log.event("ERROR", error=str(exc))
                if ready:
                    server.state.abort("server_error")
            except Exception as error:
                print(f"Tracker 오류 기록 실패: {error}", file=sys.stderr)
    finally:
        if server is not None:
            try:
                server.close()
            except Exception as exc:
                clean = False
                code = 2 if ready else 1
                print(f"Tracker 정리 실패: {exc}", file=sys.stderr)
        if log is not None:
            try:
                if ready and clean:
                    try:
                        report = server.state.prepare_report(force=code != 0)
                        write_report(root / "report.json", report)
                    except Exception as exc:
                        code = 2
                        print(f"Tracker report 저장 실패: {exc}", file=sys.stderr)
                        log.event("ERROR", error=str(exc), operation="report")
                if clean:
                    log.event("EXIT", code=code,
                              alldone=server.state.snapshot()["alldone"] if server else False,
                              t_exit=report["T_exit"] if report else None)
            except Exception as exc:
                code = 2 if ready else 1
                print(f"Tracker EXIT 기록 실패: {exc}", file=sys.stderr)
            finally:
                try:
                    log.close()
                except Exception as exc:
                    code = 2 if ready else 1
                    print(f"Tracker 로그 종료 실패: {exc}", file=sys.stderr)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
