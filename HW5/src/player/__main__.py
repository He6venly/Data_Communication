import argparse
from pathlib import Path
import re
import socket
import sys

from .bots import STRATEGIES
from .client import Player, PlayerLog


def think_type(value):
    try:
        low, high = map(float, value.split(","))
        if 18 <= low <= high <= 22:
            return low, high
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("think must be within 18,22 milliseconds")


def fault_type(value):
    match = re.fullmatch(r"(slow|badcard|badhash|quit)@(\d+),(\d+)", value)
    if match and 0 <= int(match[2]) < 45 and 1 <= int(match[3]) <= 10:
        return match[1], int(match[2]), int(match[3])
    raise argparse.ArgumentTypeError("fault must be kind@mid,r")


def address_type(value):
    try:
        host, port = value.rsplit(":", 1)
        if host and 1 <= int(port) <= 65535:
            return host, int(port)
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("crasher must be host:port")


def parser():
    # 주소랑 전략, 실행 종류를 입력받고 잘못된 값은 접속 전에 막아줌
    result = argparse.ArgumentParser(description="HW5 Card Duel Player")
    result.add_argument("--host", required=True)
    result.add_argument("--port", required=True, type=int)
    result.add_argument("--id", required=True, type=int, choices=range(1, 11))
    result.add_argument("--strategy", required=True, choices=STRATEGIES)
    result.add_argument("--think", type=think_type, default=(18.0, 22.0))
    result.add_argument("--run", required=True, choices=("A", "B", "C", "D"))
    result.add_argument("--out", required=True, type=Path)
    result.add_argument("--fault", type=fault_type)
    result.add_argument("--crasher", type=address_type)
    return result


def main(argv=None):
    # 실행값을 확인하고 로그랑 연결은 끝날 때 같이 정리해줌
    cli = parser()
    args = cli.parse_args(argv)
    if not args.host.strip() or not 1 <= args.port <= 65535:
        cli.error("valid host and port 1..65535 required")
    if args.fault and args.run != "C":
        cli.error("--fault is only available in Run C")
    if (args.crasher is not None) != (args.run == "D"):
        cli.error("--crasher is required only in Run D")
    log = None
    try:
        log = PlayerLog(args.out, args.run, args.id)
        with socket.create_connection((args.host, args.port), timeout=10) as sock:
            sock.settimeout(10)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return Player(args, sock, log).run()
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as exc:
        if log is not None:
            log("TERMINATE", "FAIL", f"reason={ascii(str(exc))}")
        print(f"Player: {exc}", file=sys.stderr)
        return 1
    finally:
        if log is not None:
            log.close()


if __name__ == "__main__":
    sys.exit(main())
