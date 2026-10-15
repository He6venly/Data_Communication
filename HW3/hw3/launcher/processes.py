"""Build and start independent Worker processes."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from hw3.common.settings import WORKER_COUNT


def build_worker_command(
    worker_id: int,
    coord: str,
    peer_ip: str,
    peer_base: int,
    step_delay: int,
    run_id: str,
    log_dir: str | Path,
) -> list[str]:
    """Return the argv list for one ``python -m hw3.worker`` process."""

    if not 1 <= worker_id <= WORKER_COUNT:
        raise ValueError(f"worker_id must be 1..{WORKER_COUNT}")
    peer_port = peer_base + worker_id
    if not 1 <= peer_port <= 65_535:
        raise ValueError("peer port must be 1..65535")
    if step_delay < 0:
        raise ValueError("step_delay must be non-negative milliseconds")
    return [
        sys.executable,
        "-m",
        "hw3.worker",
        "--id",
        str(worker_id),
        "--coord",
        coord,
        "--peer-ip",
        peer_ip,
        "--peer-port",
        str(peer_port),
        "--step-delay",
        str(step_delay),
        "--run-id",
        run_id,
        "--log-dir",
        str(log_dir),
    ]


def start_worker(
    command: Sequence[str],
    popen_factory: Callable[..., Any] | None = None,
) -> Any:
    """Start one Worker without a shell or unread output pipes."""

    factory = subprocess.Popen if popen_factory is None else popen_factory
    return factory(list(command), shell=False)


def start_workers(
    worker_count: int,
    coord: str,
    peer_ip: str,
    peer_base: int,
    step_delay: int,
    run_id: str,
    log_dir: str | Path,
    popen_factory: Callable[..., Any] | None = None,
) -> dict[int, Any]:
    if worker_count != WORKER_COUNT:
        raise ValueError(f"HW3 requires exactly {WORKER_COUNT} workers")
    processes: dict[int, Any] = {}
    try:
        for worker_id in range(1, worker_count + 1):
            command = build_worker_command(
                worker_id, coord, peer_ip, peer_base, step_delay, run_id, log_dir
            )
            processes[worker_id] = start_worker(command, popen_factory)
    except Exception:
        stop_processes(processes)
        raise
    return processes


def stop_processes(processes: dict[int, Any], wait_seconds: float = 3.0) -> None:
    """Best-effort cleanup of only the Worker processes started by Launcher."""

    running = [process for process in processes.values() if process.poll() is None]
    for process in running:
        process.terminate()
    for process in running:
        try:
            process.wait(timeout=wait_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
    for process in running:
        if process.poll() is None:
            process.wait(timeout=wait_seconds)
