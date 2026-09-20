"""로컬 Worker 4개를 각각 독립된 Thread에서 실행한다."""

import argparse
import math
import signal
import socket
import sys
import threading

from logger import initialize_log_files
from worker import Worker


def parse_args():
    """실행 인자를 읽고 접속 설정을 확인한다."""
    parser = argparse.ArgumentParser(
        description="로컬 Worker 1~4 실행",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--master-host", default="52.79.236.152", help="Master 주소")
    parser.add_argument("--master-port", type=int, default=5000, help="Master 포트")
    parser.add_argument("--peer-host", default="127.0.0.1", help="P2P 등록 주소")
    parser.add_argument("--peer-base-port", type=int, default=6000, help="P2P 기준 포트")
    parser.add_argument("--log-dir", default="logs/workers", help="로그 폴더")
    parser.add_argument("--timeout", type=float, default=60, help="소켓 제한시간(초)")
    parser.add_argument("--seed", type=int, default=None, help="Worker 난수 시드 기준값")
    args = parser.parse_args()

    if not args.master_host.strip() or not args.peer_host.strip():
        parser.error("Master와 P2P 주소는 비어 있을 수 없습니다.")
    if not 1 <= args.master_port <= 65535:
        parser.error("Master 포트는 1~65535 범위여야 합니다.")
    for worker_id in range(1, 5):
        if not 1 <= args.peer_base_port + worker_id <= 65535:
            parser.error("Worker별 P2P 포트는 1~65535 범위여야 합니다.")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout은 유한한 양수여야 합니다.")
    return args


def run_worker(worker, timeout, errors, errors_lock, stop_requested):
    """Worker를 실행하고 발생한 오류를 메인 스레드에 전달한다."""
    if stop_requested.is_set():
        return
    try:
        worker.run(timeout=timeout)
    except Exception as error:
        with errors_lock:
            errors.append((worker.worker_id, str(error)))
            print(f"Worker{worker.worker_id} 오류: {error}", file=sys.stderr, flush=True)


def shutdown_workers(workers):
    """수신 대기를 깨워 Worker.run()이 자원을 정리하도록 한다."""
    for worker in workers:
        worker.running = False
        sock = worker.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def main() -> int:
    args = parse_args()
    workers = []
    for worker_id in range(1, 5):
        worker_seed = None if args.seed is None else args.seed + worker_id
        workers.append(Worker(
            worker_id=worker_id,
            master_host=args.master_host,
            master_port=args.master_port,
            peer_host=args.peer_host,
            peer_port=args.peer_base_port + worker_id,
            log_dir=args.log_dir,
            seed=worker_seed,
        ))

    # 로그 초기화는 모든 Worker의 NodeLogger 생성 전에 한 번만 한다.
    initialize_log_files(args.log_dir)
    print(f"Master: {args.master_host}:{args.master_port}", flush=True)
    for worker in workers:
        print(f"Worker{worker.worker_id}: P2P {worker.peer_host}:{worker.peer_port}", flush=True)
    print(f"로그 폴더: {args.log_dir}", flush=True)

    errors = []
    errors_lock = threading.Lock()
    stop_requested = threading.Event()
    threads = [
        threading.Thread(
            target=run_worker,
            args=(worker, args.timeout, errors, errors_lock, stop_requested),
            name=f"Worker{worker.worker_id}",
            daemon=False,
        )
        for worker in workers
    ]

    def request_stop(signum, frame):
        # join 도중 예외를 던지지 않고 메인 스레드에서 종료를 진행한다.
        stop_requested.set()

    previous_handler = signal.signal(signal.SIGINT, request_stop)
    started_threads = []
    try:
        for thread in threads:
            thread.start()
            started_threads.append(thread)
    except Exception:
        stop_requested.set()
        raise
    finally:
        try:
            stop_announced = False
            while any(thread.is_alive() for thread in started_threads):
                if stop_requested.is_set():
                    if not stop_announced:
                        print("종료 요청: Worker 연결을 정리하고 Thread 종료를 기다립니다.", flush=True)
                        stop_announced = True
                    # 접속 중이던 Worker의 소켓이 뒤늦게 생긴 경우도 정리한다.
                    shutdown_workers(workers)
                for thread in started_threads:
                    thread.join(timeout=0.2)
        finally:
            signal.signal(signal.SIGINT, previous_handler)

    if stop_requested.is_set():
        print("사용자 종료 요청으로 실행을 종료했습니다.", flush=True)
        return 130
    with errors_lock:
        if errors:
            print(f"Worker 실행 실패: {len(errors)}개 Thread에서 오류가 발생했습니다.", file=sys.stderr)
            return 1
    print("Worker1, Worker2, Worker3, Worker4가 모두 정상 종료했습니다.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
