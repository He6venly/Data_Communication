import argparse
import secrets
import socket
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock

from .controller import PlayerController
from .scheduler import CrashScheduler


class CrasherLog:
    def __init__(self, stream):
        self.stream = stream
        self.lock = Lock()

    # 여러 Thread가 한 줄씩 섞이지 않도록 로그 쓰기를 보호한다.
    def __call__(self, event: str, status: str, message: str) -> None:
        now = datetime.now()
        timestamp = now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
        line = f"[{timestamp}] CRASHER | {event:<9} | {status:<7} | {message}\n"
        with self.lock:
            self.stream.write(line)
            self.stream.flush()


# 제어 포트를 열고 열 명의 Player에 계획한 장애를 주입한다.
def run(host: str, port: int, out: Path, seed: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "RunD_Crasher.txt"
    with log_path.open("x", encoding="ascii", newline="\n") as stream:
        log = CrasherLog(stream)
        controller = PlayerController(log)
        scheduler = CrashScheduler(controller, seed)
        log("PLAN", "INFO", scheduler.plan_message())
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((host, port))
                listener.listen(10)
                actual_host, actual_port = listener.getsockname()
                log("INIT", "SUCCESS", f"listen {actual_host}:{actual_port}")
                controller.accept_players(listener)
                scheduler.run()
        except BaseException as error:
            log("TERMINATE", "FAIL", ascii(str(error) or type(error).__name__))
            raise
        finally:
            controller.close()


# 명세에 맞는 Crasher 실행 인자를 읽는다.
def main() -> int:
    parser = argparse.ArgumentParser(description="HW5 Run D Crasher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--run", choices=("D",), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    seed = args.seed if args.seed is not None else secrets.randbelow(2**31)
    try:
        run(args.host, args.port, args.out, seed)
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        print(f"Crasher: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
