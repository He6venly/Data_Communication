"""python -m hw3.coordinator --host 0.0.0.0 --port 4575 ..."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import queue
import socket
import sys
import threading


def worker_list(values):
    return "["+" ".join(f"W{i}" for i in values)+"]"


def console_message(event):
    """Compact presentation of actual decisions; complete JSON stays in files."""
    f, kind = event.fields, event.kind
    if kind == "POOL":
        return (f"DONE={f['done']}/1000 | PENDING={f['pending']} | ASSIGNED={f['assigned']} | QUEUE={f['queue']}\n"
                f"    ALIVE({f['alive']})={worker_list(f['alive_workers'])} "
                f"SUSPECT={worker_list(f['suspect_workers'])} DEAD={worker_list(f['dead_workers'])}")
    if kind == "INIT":
        return (f"{f['host']}:{f['port']} | Worker={f['workers']} | Dispatcher={f['dispatchers']} "
                f"| Task Lock={f['task_locks']}")
    if kind == "RING":
        return f"Buddy 주소 전송 완료 | Worker={f['workers']}"
    if kind == "START":
        return f"RING_OK={f['ring_ready']}/10 | 계산 시작 허용"
    if kind == "SUSPECT":
        return f"W{f['worker']} | HB 없음 {f['detection_delay_ms']/1000:.2f}s | SUSPECT (인계 없음)"
    if kind == "ALIVE":
        return f"W{f['worker']} | HB 회복 -> ALIVE"
    if kind == "DEAD":
        return (f"W{f['worker']} | HB 없음 {f['detection_delay_ms']/1000:.2f}s | DEAD | 인계 대상 W{f['to_worker']}\n"
                f"    소유 Task={f['owned_tasks']} | DEAD={worker_list(f['dead_now'])}")
    if kind == "TAKEOVER":
        return (f"Task={f['task']} | 소유권 W{f['from_worker']} -> W{f['to_worker']} "
                f"| epoch={f['old_epoch']} -> {f['epoch']}")
    if kind == "REJOIN":
        return f"W{f['worker']} | 재합류 승인 #{f['rejoin_count']} -> ALIVE | PENDING={f['pending']}"
    if kind == "ASSIGN":
        label = f"재합류 #{f['rejoin_count']} 첫 새 배정" if f['rejoin_count'] else "초기 배정"
        return (f"W{f['worker']} | {label} "
                f"| Task={f['task']} | epoch={f['epoch']}")
    if kind == "COMMIT":
        return (f"Task={f['task']} | W{f['worker']} | epoch={f['epoch']} "
                f"| 반영 완료 | commit_count={f['commit_count']} | result={f['result']:,}")
    if kind == "NO_TASK":
        return f"W{f['worker']} | 재합류 #{f['rejoin_count']} | PENDING=0 | 인계 또는 종료 대기"
    if kind == "VERIFY":
        result = "PASS" if f['pass'] else "FAIL"
        once = "PASS" if f['all_commit_once'] else "FAIL"
        return (f"{result} | DONE={f['done']}/1000 | COMMIT={f['commits']} | DOUBLE_COMMIT={f['double_commit']}\n"
                f"    SUM={f['sum']:,} | 모든 Task commit_count=1 검사: {once}")
    if kind == "ERROR":
        return f"실행 오류 | {f['error']}"
    if kind == "TERMINATE":
        state = "정상 종료" if event.status == "SUCCESS" else "종료 실패"
        return f"{state} | 남은 Thread={f['threads_alive']} | error={f['error']}"
    return json.dumps(f, ensure_ascii=False, separators=(",", ":"))


class Coordinator:
    def __init__(self, host, port, logger, *, console=True):
        from .tables import Tables
        self.host, self.port, self.logger = host, port, logger
        self.console = console
        self.tables = Tables()
        self.requests = queue.Queue()
        self.stop_event = threading.Event()
        self.finishing = threading.Event()
        self.started = threading.Event()
        self.detector_stop = threading.Event()
        self.output_lock = threading.Lock()
        self.console_rejoin_tasks = {}
        self.failure_lock = threading.Lock()
        self.error = None
        self.server = None
        self.threads = []

    def publish(self, events):
        for event in events:
            with self.output_lock:
                self.logger.write(event.kind, event.status, event.fields)
                if not self.console:
                    continue
                show = event.kind in {"INIT", "RING", "START", "POOL", "SUSPECT", "ALIVE", "DEAD",
                                      "TAKEOVER", "REJOIN", "VERIFY", "ERROR", "TERMINATE"}
                if event.kind in {"ASSIGN", "NO_TASK"} and event.fields.get("rejoin_count", 0) > 0:
                    cycle = (event.fields["worker"], event.fields["rejoin_count"])
                    show = cycle not in self.console_rejoin_tasks
                    if show:
                        self.console_rejoin_tasks[cycle] = event.fields.get("task")
                elif event.kind == "ASSIGN":
                    show = event.fields["task"] < 10
                elif event.kind == "COMMIT":
                    f = event.fields
                    show = (f["task"] < 10 or f["epoch"] > 1 or
                            self.console_rejoin_tasks.get((f["worker"], f["rejoin_count"])) == f["task"])
                if show:
                    now = datetime.now(timezone(timedelta(hours=9)))
                    clock = now.strftime("%H:%M:%S.")+f"{now.microsecond//1000:03d}"
                    elapsed = event.fields.get("elapsed_ms")
                    prefix = "" if elapsed is None else f"t={elapsed/1000:.1f}s | "
                    message = console_message(event)
                    if event.kind == "INIT":
                        message += f"\n    run_id={getattr(self.logger, 'run_id', '')} | 시각=KST"
                    print(f"[{clock}] COORD | {event.kind} | {event.status} | {prefix}{message}", flush=True)

    def emit(self, kind, status="INFO", **fields):
        self.publish([self.tables.event(kind, status, **fields)])

    def fail(self, error):
        with self.failure_lock:
            first = self.error is None
            if first:
                self.error = str(error)
        self.finishing.set()
        self.detector_stop.set()
        self.started.set()
        with self.tables.ready:
            self.tables.ready.notify_all()
        with self.tables.done:
            self.tables.done.notify_all()
        if first:
            self.emit("ERROR", "FAIL", error=self.error)

    def sender(self, channel, message):
        with self.tables.lock:
            worker_id = channel.worker_id
            valid = worker_id is not None and self.tables.workers[worker_id].channel is channel
        if valid and message.kind in {"HB", "REQ", "REJOIN", "RING_OK"}:
            valid = int(message.fields[0]) == worker_id
        if not valid:
            self.emit("PROTOCOL", "WARN", message="unregistered/mismatched sender", message_kind=message.kind)
            return None
        return worker_id

    def send(self, channel, kind, fields=()):
        from hw3.common.protocol import Message, encode
        from hw3.common.transport import send_line
        if channel is None:
            self.fail(ConnectionError(f"{kind}: missing Worker channel"))
            return False
        try:
            # RLock allows the common helper to take the same socket lock again.
            # This also keeps a delayed dispatcher reply from following BYE.
            with channel.send_lock:
                if self.finishing.is_set() and kind != "BYE":
                    return False
                send_line(channel.sock, encode(Message(kind, tuple(map(str, fields)))), channel.send_lock)
            return True
        except OSError as error:
            if not self.finishing.is_set():
                self.fail(error)
            return False

    def _thread(self, name, target):
        def guarded():
            try:
                target(self)
            except Exception as error:
                self.fail(f"{name}: {error}")
        thread = threading.Thread(name=name, target=guarded)
        self.threads.append(thread)
        thread.start()

    def run(self):
        from hw3.common.settings import DISPATCHER_COUNT, CONTRACT_VERSION
        from .listener import listener_loop
        from .dispatcher import dispatcher_loop
        from .detector import detector_loop
        success = False
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.bind((self.host, self.port))
            self.server.listen(16)
            self.server.setblocking(False)
            self.emit("INIT", host=self.host, port=self.server.getsockname()[1], workers=len(self.tables.workers),
                      dispatchers=DISPATCHER_COUNT, task_locks=len({id(t.lock) for t in self.tables.tasks}),
                      contract_version=CONTRACT_VERSION)
            self._thread("Coordinator Listener", listener_loop)
            for i in range(DISPATCHER_COUNT):
                self._thread(f"Coordinator Dispatcher {i+1}", dispatcher_loop)
            self._thread("Coordinator FD", detector_loop)
            with self.tables.ready:
                self.tables.ready.wait_for(lambda: self.error is not None or
                                            all(w.channel is not None for w in self.tables.workers.values()))
                if self.error is None:
                    self.tables.phase = "RING"
                    rings = [(w.channel, ((i % len(self.tables.workers)) + 1,
                                          *self.tables.workers[(i % len(self.tables.workers)) + 1].peer))
                             for i, w in self.tables.workers.items()]
                else:
                    rings = []
            for channel, fields in rings:
                self.send(channel, "RING", fields)
            if self.error is not None:
                return False
            self.emit("RING", workers=len(rings))
            with self.tables.ready:
                self.tables.ready.wait_for(lambda: self.error is not None or
                                            all(w.ring_ok for w in self.tables.workers.values()))
            if self.error is not None:
                return False
            self.publish([self.tables.begin()])
            for worker in self.tables.workers.values():
                self.send(worker.channel, "START")
            with self.tables.lock:
                self.tables.detector_enabled = self.error is None
            self.started.set()
            with self.tables.done:
                self.tables.done.wait_for(lambda: self.error is not None or
                                         self.tables.done_count == len(self.tables.tasks))
            self.finishing.set()
            self.detector_stop.set()
            with self.tables.lock:
                self.tables.detector_enabled = False
            if self.error is None:
                summary = self.tables.verify()
                self.emit("VERIFY", "SUCCESS" if summary["pass"] else "FAIL", **summary)
                self.emit("SUMMARY", "INFO", **self.tables.metrics())
                success = summary["pass"]
        except KeyboardInterrupt:
            self.fail("interrupted")
        except Exception as error:
            self.fail(error)
        finally:
            self.close()
            self.emit("TERMINATE", "SUCCESS" if success and self.error is None else "FAIL",
                      error=self.error, threads_alive=sum(t.is_alive() for t in self.threads))
            self.logger.close()
        return success and self.error is None

    def close(self):
        from .dispatcher import STOP
        self.finishing.set()
        self.detector_stop.set()
        self.started.set()
        for worker in self.tables.workers.values():
            if worker.channel is not None:
                if self.send(worker.channel, "BYE"):
                    self.emit("BYE", worker=worker.channel.worker_id)
        dispatchers = sum(t.name.startswith("Coordinator Dispatcher") for t in self.threads)
        for _ in range(dispatchers):
            self.requests.put(STOP)
        self.stop_event.set()
        for thread in self.threads:
            thread.join()
        if self.server is not None:
            self.server.close()


def arguments(argv=None):
    from hw3.common.settings import COORDINATOR_PORT
    parser = argparse.ArgumentParser(description="HW3 Coordinator")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=COORDINATOR_PORT)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--quiet", action="store_true", help="write complete logs without console summaries")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or not args.run_id:
        parser.error("invalid port or empty run id")
    return args


def main(argv=None):
    if sys.version_info < (3, 12):
        print("Python 3.12 이상이 필요합니다.", file=sys.stderr)
        return 2
    try:
        from hw3.common.log import NodeLogger
        args = arguments(argv)
    except ModuleNotFoundError as error:
        if error.name and error.name.startswith("hw3.common"):
            print("확정된 hw3.common 구현을 먼저 통합하세요.", file=sys.stderr)
            return 2
        raise
    logger = NodeLogger("COORD", args.log_dir / "Coordinator.txt", args.run_id)
    return 0 if Coordinator(args.host, args.port, logger, console=not args.quiet).run() else 1


if __name__ == "__main__":
    raise SystemExit(main())
