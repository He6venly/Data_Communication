import argparse
from dataclasses import replace
import math
from pathlib import Path
import re
import socket
import sys
import time

from .board import Board, ROUNDS
from .log import WorkerLog
from .transport import Connection, PhaseTimeout, ProtocolError, connect


def positive_float(value):
    try:
        number = float(value)
        if math.isfinite(number) and number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("양의 유한한 수가 필요합니다")


def port_number(value):
    try:
        number = int(value)
        if 1 <= number <= 65535:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("포트는 1~65535여야 합니다")


def nonempty(value):
    if not value.strip():
        raise argparse.ArgumentTypeError("빈 값은 사용할 수 없습니다")
    return value


def run_id_type(value):
    # 영문이나 숫자로 시작하고 허용된 문자로 64자 안에 적었는지 확인함
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value, flags=re.ASCII):
        return value
    raise argparse.ArgumentTypeError("실행 식별자는 영문·숫자로 시작하는 1~64자의 영문·숫자·_·-만 허용합니다")


def parser():
    # 실행 경로랑 접속할 주소, 통신 제한시간을 실행할 때 입력받음
    result = argparse.ArgumentParser(description="ASCII Evolution Worker")
    result.add_argument("--host", required=True, type=nonempty)
    result.add_argument("--port", required=True, type=port_number)
    result.add_argument("--log-dir", required=True, type=Path)
    result.add_argument("--run-id", required=True, type=run_id_type)
    result.add_argument("--connect-timeout", type=positive_float, default=10.0)
    result.add_argument("--startup-timeout", type=positive_float, default=300.0)
    result.add_argument("--io-timeout", type=positive_float, default=120.0)
    return result


def execute(args):
    # 스레드 하나로 배정받고 계산해서 보내는 걸 반복한 다음 끝나면 연결을 닫아줌
    log = WorkerLog(args.log_dir, args.run_id)
    sock = None
    assignment = None
    completed, total_ms = 0, 0.0
    r = None
    try:
        log.write("INIT", "SUCCESS", connect_timeout_s=args.connect_timeout,
                  startup_timeout_s=args.startup_timeout, io_timeout_s=args.io_timeout)
        sock = connect(args.host, args.port, args.connect_timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        connection = Connection(sock)
        log.write("CONNECT", "SUCCESS", host=args.host, port=args.port)
        startup_deadline = time.monotonic() + args.startup_timeout
        connection.send(b"HELLO\n", startup_deadline, "startup", args.startup_timeout)
        assignment = connection.assignment(startup_deadline, args.startup_timeout)
        a = assignment
        log.bind(a.k)
        log.write("ASSIGN", "SUCCESS", k=a.k, n=a.n, y0=a.y0, y1=a.y1,
                  h=a.y1-a.y0, team=a.team)
        board = Board(a.rows, a.canvas1, a.canvas2, a.y0, a.team)
        assignment = a = replace(a, rows=[], canvas1=[], canvas2=[])
        window = []
        for r in range(ROUNDS):
            phase = "startup" if r == 0 else "recv"
            timeout = args.startup_timeout if r == 0 else args.io_timeout
            deadline = startup_deadline if r == 0 else time.monotonic() + timeout
            top, bottom = connection.round(r, deadline, phase, timeout)
            start = time.perf_counter()
            board.step(r, top, bottom)
            if r in (1000, 2000):
                log.write("REPAINT", "INFO", round=r, canvas=f"canvas{r//1000}.txt",
                          conversion="brian" if r == 1000 else "cyclic")
            connection.send(board.result(r, a.k), time.monotonic() + args.io_timeout,
                            "send", args.io_timeout)
            elapsed = (time.perf_counter() - start) * 1000
            completed += 1
            total_ms += elapsed
            window.append(elapsed)
            if completed % 100 == 0:
                log.write("ROUND", "INFO", k=a.k, r_start=r-99, r_end=r, count=100,
                          compute_avg_ms=sum(window)/100, compute_max_ms=max(window))
                window.clear()
        if connection.line(time.monotonic() + args.io_timeout, "recv", args.io_timeout) != "BYE":
            raise ProtocolError("3000회 완료 뒤 BYE가 필요합니다")
        log.write("TERMINATE", "SUCCESS", k=a.k, rounds_completed=completed,
                  compute_avg_ms=total_ms/completed)
        return 0
    except (OSError, ValueError, EOFError, KeyboardInterrupt) as exc:
        fields = {"reason": "interrupted" if isinstance(exc, KeyboardInterrupt) else str(exc),
                  "rounds_completed": completed, "compute_avg_ms": total_ms/completed if completed else 0.0}
        if assignment is not None:
            fields["k"] = assignment.k
        if r is not None:
            fields["round"] = r
        if isinstance(exc, PhaseTimeout):
            fields.update(reason="timeout", phase=exc.phase, timeout_s=exc.timeout_s)
        try:
            log.write("TERMINATE", "FAIL", **fields)
        except OSError:
            pass
        print(f"Worker 실패: {fields}", file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        if sock is not None:
            sock.close()
        log.close()


def main(argv=None):
    return execute(parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
