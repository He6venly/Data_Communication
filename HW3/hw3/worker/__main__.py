# Worker를 실행하고 종료한다.

import argparse
import os
from pathlib import Path
import sys


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="HW3 Worker")
    parser.add_argument("--id", type=int, required=True, choices=range(1, 11))
    parser.add_argument("--coord", required=True, metavar="HOST:PORT")
    parser.add_argument("--peer-ip", default="127.0.0.1")
    parser.add_argument("--peer-port", type=int, required=True)
    parser.add_argument("--step-delay", type=int, default=100, help="step당 지연 시간(ms)")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--log-dir", required=True)
    args = parser.parse_args(argv)
    try:
        host, port = args.coord.rsplit(":", 1)
        args.coordinator = (host, int(port))
        if not host or not 1 <= args.coordinator[1] <= 65_535:
            raise ValueError
    except ValueError:
        parser.error("--coord must be HOST:PORT with port 1..65535")
    if not 1 <= args.peer_port <= 65_535 or args.step_delay < 0 or not args.run_id:
        parser.error("invalid peer port, step delay, or run id")
    return args


def main(argv=None):
    args = arguments(argv)
    if sys.version_info < (3, 12):
        print("Python 3.12 이상이 필요합니다.", file=sys.stderr)
        return 2
    from hw3.common.log import NodeLogger
    from hw3.common.settings import CONTRACT_VERSION
    from .network import Worker, WorkerConfig
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = NodeLogger(f"Worker{args.id}", log_dir / f"Worker{args.id}.txt", args.run_id)
    config = WorkerConfig(args.id, args.coordinator, args.peer_ip, args.peer_port,
                          args.step_delay, args.run_id, str(log_dir))
    worker = Worker(config, logger)
    worker.emit("INIT", node=f"Worker{args.id}", pid=os.getpid(), coordinator=args.coord,
                peer_ip=args.peer_ip, peer_port=args.peer_port, step_delay_ms=args.step_delay,
                contract_version=CONTRACT_VERSION)
    try:
        worker.start()
        worker.state.stop_event.wait()
    except KeyboardInterrupt:
        worker.stop()
    except Exception as error:
        worker.fail(error)
    finally:
        worker.close()
    return 1 if worker.error else 0


if __name__ == "__main__":
    raise SystemExit(main())
