"""Command-line entry point for the HW3 Chaos Launcher."""

from __future__ import annotations

import argparse
import selectors
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hw3.common.log import NodeLogger
from hw3.common.protocol import Message, ProtocolError, encode, parse
from hw3.common.settings import (
    CONNECT_RETRY_SECONDS,
    CONTRACT_VERSION,
    COORDINATOR_PORT,
    DEFAULT_STEP_DELAY_MS,
    PEER_BASE_PORT,
    WORKER_COUNT,
)
from hw3.common.transport import send_line
from hw3.launcher.chaos import ChaosController, WorkerStatus
from hw3.launcher.processes import start_workers, stop_processes


@dataclass(slots=True)
class LauncherConfig:
    coord: str
    workers: int
    peer_ip: str
    peer_base: int
    step_delay: int
    seed: int
    run_id: str
    log_dir: Path


class Launcher:
    def __init__(self, config: LauncherConfig) -> None:
        self.config = config
        self.controller = ChaosController(config.workers, config.seed)
        self.selector = selectors.DefaultSelector()
        self.processes: dict[int, Any] = {}
        self.send_locks = {i: threading.Lock() for i in range(1, config.workers + 1)}
        self.logger = NodeLogger("LAUNCHER", config.log_dir / "Launcher.txt", config.run_id)
        self._injection_end_logged = False

    def run(self) -> None:
        normal_exit = False
        try:
            self._log_init()
            self.processes = start_workers(
                self.config.workers,
                self.config.coord,
                self.config.peer_ip,
                self.config.peer_base,
                self.config.step_delay,
                self.config.run_id,
                self.config.log_dir,
            )
            for worker_id, process in self.processes.items():
                self.controller.workers[worker_id].process = process
                self.logger.write(
                    "PROCESS_START",
                    "SUCCESS",
                    {
                        "worker": worker_id,
                        "pid": process.pid,
                        "peer_port": self.config.peer_base + worker_id,
                    },
                )
            self._connect_controls()
            self._event_loop()
            normal_exit = True
            self.logger.write(
                "TERMINATE", "SUCCESS", {"exited_workers": self.config.workers}
            )
        except Exception as error:
            self.logger.write(
                "TERMINATE",
                "FAIL",
                {"error_type": type(error).__name__, "error": str(error)},
            )
            raise
        finally:
            self._close_controls()
            if not normal_exit:
                stop_processes(self.processes)
            self.selector.close()
            self.logger.close()

    def _log_init(self) -> None:
        self.logger.write(
            "INIT",
            "INFO",
            {
                "contract_version": CONTRACT_VERSION,
                "seed": self.config.seed,
                "workers": self.config.workers,
                "coord": self.config.coord,
                "peer_ip": self.config.peer_ip,
                "peer_base": self.config.peer_base,
                "step_delay_ms": self.config.step_delay,
            },
        )

    def _connect_controls(self) -> None:
        for worker_id in range(1, self.config.workers + 1):
            process = self.processes[worker_id]
            address = (self.config.peer_ip, self.config.peer_base + worker_id)
            while True:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Worker {worker_id} exited before its control connection was ready"
                    )
                try:
                    control = socket.create_connection(address, timeout=1.0)
                    break
                except (ConnectionRefusedError, TimeoutError, OSError):
                    time.sleep(CONNECT_RETRY_SECONDS)
            send_line(control, encode(Message("LAUNCHER")), self.send_locks[worker_id])
            control.setblocking(False)
            slot = self.controller.workers[worker_id]
            slot.control_socket = control
            self.selector.register(control, selectors.EVENT_READ, worker_id)
            self.logger.write(
                "CONNECT",
                "SUCCESS",
                {"worker": worker_id, "peer_ip": address[0], "peer_port": address[1]},
            )

    def _event_loop(self) -> None:
        while not self.controller.all_exited:
            now = time.monotonic()
            if self.controller.finish_if_cutoff(now):
                self._log_injection_end(now)
            self._send_due_restarts(now)
            self._send_due_crash(now)
            if self.controller.injection_finished:
                self._log_injection_end(now)

            deadline = self.controller.next_deadline()
            timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
            for key, _ in self.selector.select(timeout):
                self._receive(key.data, key.fileobj)
        if not self._injection_end_logged and self.controller.t0 is not None:
            self.controller.finish_injection()
            self._log_injection_end(time.monotonic())

    def _send_due_restarts(self, now: float) -> None:
        for worker_id in self.controller.due_restarts(now):
            if self._send_command(worker_id, "RESTART"):
                slot = self.controller.workers[worker_id]
                self.logger.write(
                    "RESTART",
                    "INFO",
                    {
                        "worker": worker_id,
                        "crash_count": slot.crash_count,
                        "down": list(self.controller.down_workers),
                    },
                )

    def _send_due_crash(self, now: float) -> None:
        plan = self.controller.due_crash(now)
        if plan is None:
            return
        if self._send_command(plan.worker_id, "CRASH"):
            self.logger.write(
                "CRASH",
                "INFO",
                {
                    "worker": plan.worker_id,
                    "crash_count": plan.crash_count,
                    "candidates": list(plan.candidates),
                    "down": list(plan.down),
                    "downtime_ms": round(plan.downtime * 1000),
                },
            )

    def _send_command(self, worker_id: int, kind: str) -> bool:
        slot = self.controller.workers[worker_id]
        try:
            send_line(slot.control_socket, encode(Message(kind)), self.send_locks[worker_id])
            return True
        except OSError as error:
            self.logger.write(
                "SEND", "FAIL", {"worker": worker_id, "command": kind, "error": str(error)}
            )
            self._mark_eof(worker_id, slot.control_socket)
            return False

    def _receive(self, worker_id: int, control: socket.socket) -> None:
        try:
            data = control.recv(65_536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._mark_eof(worker_id, control)
            return
        slot = self.controller.workers[worker_id]
        try:
            lines = slot.line_buffer.feed(data)
        except UnicodeDecodeError as error:
            self.logger.write(
                "PROTOCOL", "WARN", {"worker": worker_id, "error": str(error)}
            )
            return
        for line in lines:
            self._handle_message(worker_id, line)

    def _handle_message(self, worker_id: int, line: str) -> None:
        try:
            message = parse(line)
        except ProtocolError as error:
            self.logger.write(
                "PROTOCOL", "WARN", {"worker": worker_id, "line": line, "error": str(error)}
            )
            return
        claimed_worker = int(message.fields[0]) if message.fields else None
        if message.kind not in {"READY", "REJOINED"} or claimed_worker != worker_id:
            self.logger.write(
                "PROTOCOL",
                "WARN",
                {"worker": worker_id, "message": line, "reason": "unexpected launcher message"},
            )
            return
        now = time.monotonic()
        if message.kind == "READY":
            started = self.controller.mark_ready(worker_id, now)
            fields: dict[str, object] = {
                "worker": worker_id,
                "ready_count": self.controller.ready_count,
            }
            if started:
                fields.update(
                    {
                        "t0_monotonic": self.controller.t0,
                        "first_crash_in_ms": round(
                            (self.controller.next_crash - self.controller.t0) * 1000
                        ),
                    }
                )
            self.logger.write("READY", "SUCCESS", fields)
        elif self.controller.mark_rejoined(worker_id, now):
            slot = self.controller.workers[worker_id]
            self.logger.write(
                "REJOINED",
                "SUCCESS",
                {
                    "worker": worker_id,
                    "crash_count": slot.crash_count,
                    "down": list(self.controller.down_workers),
                },
            )

    def _mark_eof(self, worker_id: int, control: socket.socket) -> None:
        slot = self.controller.workers[worker_id]
        if slot.status is WorkerStatus.EXITED:
            return
        try:
            self.selector.unregister(control)
        except KeyError:
            pass
        control.close()
        self.controller.mark_exited(worker_id)
        self.logger.write(
            "EOF",
            "INFO",
            {"worker": worker_id, "state": "EXITED", "down": list(self.controller.down_workers)},
        )
        if self.controller.t0 is None:
            raise RuntimeError(f"Worker {worker_id} exited before all Workers were READY")

    def _log_injection_end(self, now: float) -> None:
        if self._injection_end_logged or self.controller.t0 is None:
            return
        self._injection_end_logged = True
        self.logger.write(
            "INJECTION_END",
            "INFO",
            {"elapsed_ms": round((now - self.controller.t0) * 1000)},
        )

    def _close_controls(self) -> None:
        for slot in self.controller.workers.values():
            if slot.control_socket is not None:
                try:
                    slot.control_socket.close()
                except OSError:
                    pass


def parse_coord(value: str) -> str:
    host, separator, port_text = value.rpartition(":")
    if not separator or not host or any(char.isspace() for char in host):
        raise argparse.ArgumentTypeError("coord must be HOST:PORT")
    try:
        port = int(port_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("coord port must be an integer") from error
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("coord port must be 1..65535")
    if port != COORDINATOR_PORT:
        raise argparse.ArgumentTypeError(
            f"HW3 Coordinator port must be {COORDINATOR_PORT}"
        )
    return f"{host}:{port}"


def non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be an integer") from error
    if number < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HW3 Chaos Launcher")
    parser.add_argument("--coord", required=True, type=parse_coord)
    parser.add_argument("--workers", type=int, default=WORKER_COUNT)
    parser.add_argument("--peer-ip", default="127.0.0.1")
    parser.add_argument("--peer-base", type=int, default=PEER_BASE_PORT)
    parser.add_argument("--step-delay", type=non_negative_int, default=DEFAULT_STEP_DELAY_MS)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.workers != WORKER_COUNT:
        parser.error(f"--workers must be exactly {WORKER_COUNT}")
    if not (1 <= args.peer_base + 1 <= args.peer_base + args.workers <= 65_535):
        parser.error("peer port range must stay within 1..65535")
    config = LauncherConfig(
        coord=args.coord,
        workers=args.workers,
        peer_ip=args.peer_ip,
        peer_base=args.peer_base,
        step_delay=args.step_delay,
        seed=args.seed,
        run_id=args.run_id,
        log_dir=args.log_dir,
    )
    Launcher(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
