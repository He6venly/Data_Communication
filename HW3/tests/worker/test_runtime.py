# Worker 통신과 장애·복구·종료를 테스트한다.

from collections import deque
import json
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from hw3.common.protocol import Message, parse
from hw3.worker.network import Channel, Worker, WorkerConfig
from hw3.worker.heartbeat import heartbeat_loop
from hw3.worker.primes import count_step


class MemoryLogger:
    def __init__(self):
        self.cv = threading.Condition()
        self.records = []
        self.closed = False

    def write(self, event, status, fields):
        with self.cv:
            self.records.append((event, status, fields))
            self.cv.notify_all()

    def wait(self, event, *, timeout=3, **fields):
        deadline = time.monotonic() + timeout
        with self.cv:
            while True:
                for kind, _, record in self.records:
                    if kind == event and all(record.get(k) == v for k, v in fields.items()):
                        return record
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"missing log {event} {fields}; {self.records[-5:]}")
                self.cv.wait(remaining)

    def close(self):
        self.closed = True


def listener():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    sock.settimeout(4)
    return sock


class Wire:
    def __init__(self, sock):
        self.sock = sock
        self.sock.settimeout(0.05)
        self.buffer = b""
        self.inbox = deque()
        self.history = []

    def send(self, text):
        self.sock.sendall((text + "\n").encode())

    def pump(self):
        try:
            data = self.sock.recv(65536)
        except socket.timeout:
            return
        if not data:
            raise EOFError
        self.buffer += data
        lines = self.buffer.split(b"\n")
        self.buffer = lines.pop()
        for line in lines:
            message = parse(line.decode())
            self.inbox.append(message)
            self.history.append(message)

    def receive(self, kind, timeout=4, **fields):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for message in list(self.inbox):
                if message.kind == kind and all(message.fields[int(k)] == str(v) for k, v in fields.items()):
                    self.inbox.remove(message)
                    return message
            self.pump()
        raise AssertionError(f"missing {kind} {fields}; received {self.history[-10:]}")

    def quiet(self, duration=0.15):
        start = len(self.history)
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            self.pump()
        return self.history[start:]

    def close(self):
        self.sock.close()


class Harness:
    def __init__(self, *, worker_id=5, delay=10):
        self.coord_listener, self.buddy_listener = listener(), listener()
        self.logger = MemoryLogger()
        reservation = listener()
        port = reservation.getsockname()[1]
        reservation.close()
        self.worker = Worker(WorkerConfig(worker_id, self.coord_listener.getsockname(),
                                         "127.0.0.1", port, delay, "test", "unused"), self.logger)
        self.wires = []
        self.allow_failure = False

    def start(self, launcher_first=True):
        self.worker.start()
        self.coord = Wire(self.coord_listener.accept()[0])
        self.wires.append(self.coord)
        self.coord.receive("HELLO")
        target = self.buddy_listener.getsockname()
        self.coord.send(f"RING {self.worker.config.worker_id % 10 + 1} {target[0]} {target[1]}")
        self.buddy = Wire(self.buddy_listener.accept()[0])
        self.wires.append(self.buddy)
        self.buddy.receive("PEER")
        self.coord.receive("RING_OK")
        if launcher_first:
            self.connect_launcher()
        self.coord.send("START")
        self.coord.receive("REQ")
        if launcher_first:
            self.launcher.receive("READY")
        return self

    def connect_launcher(self):
        self.launcher = Wire(socket.create_connection(self.worker.listener.getsockname(), timeout=1))
        self.wires.append(self.launcher)
        self.launcher.send("LAUNCHER")
        self.logger.wait("CONNECT", role="launcher")

    def predecessor(self):
        peer = Wire(socket.create_connection(self.worker.listener.getsockname(), timeout=1))
        self.wires.append(peer)
        peer.send(f"PEER {(self.worker.config.worker_id - 2) % 10 + 1}")
        self.logger.wait("CONNECT", role="peer")
        return peer

    def close(self):
        try:
            if not self.worker.state.stop_event.is_set() and hasattr(self, "coord"):
                self.coord.send("BYE")
                self.worker.state.stop_event.wait(2)
        finally:
            self.worker.close()
            for wire in self.wires:
                wire.close()
            self.coord_listener.close()
            self.buddy_listener.close()
        if self.worker.error and not self.allow_failure:
            raise AssertionError(self.worker.error)
        if any(thread.is_alive() for thread in self.worker.threads):
            raise AssertionError("Worker thread leaked")


class RuntimeTests(unittest.TestCase):
    def make(self, **kwargs):
        harness = Harness(**kwargs)
        self.addCleanup(harness.close)
        return harness.start()

    def test_normal_fragmented_assign_ckpts_result_and_late_ack(self):
        h = self.make()
        h.coord.sock.sendall(b"ASS")
        h.coord.sock.sendall(b"IGN 0 1\n")
        result = h.coord.receive("RESULT")
        self.assertEqual(result.fields, ("0", "1", "9592"))
        partial = 0
        for step in range(1, 10):
            partial += count_step(0, step)
            self.assertEqual(h.buddy.receive("CKPT").fields, ("0", "1", str(step), str(partial)))
        h.coord.receive("REQ")
        h.coord.send("ASSIGN 152 1\nACK 0")
        self.assertEqual(h.coord.receive("RESULT").fields, ("152", "1", "6075"))

    def test_no_task_takeover_ckpt_resume_fifo_and_no_new_req(self):
        h = self.make(delay=20)
        prev = h.predecessor()
        partial = sum(count_step(152, s) for s in range(1, 7))
        prev.send(f"CKPT 152 1 6 {partial}")
        h.logger.wait("CKPT", direction="receive", task=152)
        h.coord.send("ASSIGN 0 1\nTAKEOVER 152 2 from=4\nTAKEOVER 160 2 from=4\nNO_TASK")
        results = [h.coord.receive("RESULT").fields for _ in range(3)]
        self.assertEqual(results, [("0", "1", "9592"), ("152", "2", "6075"), ("160", "2", "5989")])
        resumed = h.logger.wait("TAKEOVER", task=152)
        self.assertEqual((resumed["ckpt_epoch"], resumed["resume_step"], resumed["partial"]), (1, 7, partial))
        self.assertEqual(h.logger.wait("TAKEOVER", task=160)["resume_step"], 1)
        self.assertFalse(any(m.kind == "REQ" for m in h.coord.quiet()))
        self.assertEqual(sum(m.kind == "REQ" for m in h.coord.history), 1)

    def test_repeated_crash_silence_retry_later_rejoin_ckpt_loss_and_bye(self):
        h = self.make(delay=40)
        prev = h.predecessor()
        prev.send("CKPT 152 1 6 3600")
        h.logger.wait("CKPT", direction="receive", task=152)
        h.coord.send("ASSIGN 0 1")
        h.buddy.receive("CKPT")
        for cycle in (1, 2):
            h.launcher.send("CRASH")
            h.logger.wait("CRASH", crash_count=cycle)
            with h.worker.state.locked():
                self.assertFalse(h.worker.state.store or h.worker.state.queue or h.worker.state.current)
            h.coord.quiet(0.1)
            h.buddy.quiet(0.1)
            h.coord.send("ASSIGN 271 1\nTAKEOVER 160 2 from=4\nNO_TASK")
            prev.send("CKPT 271 1 1 500")
            self.assertEqual(h.coord.quiet(0.2), [])
            self.assertEqual(h.buddy.quiet(0.2), [])
            self.assertEqual(h.worker.state.mode, "CRASHED")
            h.launcher.send("RESTART")
            h.coord.receive("REJOIN")
            if cycle == 1:
                h.coord.send("RETRY_LATER")
                h.logger.wait("RETRY_LATER")
                self.assertFalse(any(m.kind == "REJOIN" for m in h.coord.quiet(0.3)))
                h.coord.receive("REJOIN", timeout=3)
            prev.send("CKPT 271 1 1 500")
            h.logger.wait("CKPT", direction="receive", task=271)
            self.assertEqual(h.worker.state.mode, "REJOINING")
            self.assertFalse(any(m.kind in {"HB", "RESULT", "REQ"} for m in h.coord.quiet()))
            h.coord.send("WELCOME")
            h.launcher.receive("REJOINED")
            h.coord.receive("REQ")
            h.coord.send("NO_TASK\nTAKEOVER 152 2 from=4")
            self.assertEqual(h.coord.receive("RESULT").fields, ("152", "2", "6075"))
        self.assertTrue(all(r[2]["resume_step"] == 1 for r in h.logger.records if r[0] == "TAKEOVER"))
        h.launcher.send("CRASH")
        h.logger.wait("CRASH", crash_count=3)
        h.coord.send("BYE")
        self.assertTrue(h.worker.state.stop_event.wait(2))

    def test_ready_waits_for_late_launcher_and_only_once(self):
        h = Harness()
        self.addCleanup(h.close)
        h.start(launcher_first=False)
        self.assertFalse(h.worker.state.ready_sent)
        h.connect_launcher()
        self.assertEqual(h.launcher.receive("READY").fields, ("5",))
        h.coord.send("START")
        self.assertEqual(h.launcher.quiet(), [])

    def test_takeovers_before_welcome_wait_in_fifo_and_resume_checkpoint(self):
        h = self.make()
        prev = h.predecessor()
        h.launcher.send("CRASH")
        h.logger.wait("CRASH", crash_count=1)
        h.coord.quiet()
        h.launcher.send("RESTART")
        h.coord.receive("REJOIN")
        partial = sum(count_step(0, s) for s in range(1, 6))
        prev.send(f"CKPT 0 1 5 {partial}")
        h.logger.wait("CKPT", direction="receive", task=0, step=5)
        h.coord.send("TAKEOVER 0 2 from=4\nTAKEOVER 152 2 from=4\nTAKEOVER 0 2 from=4")
        with h.worker.state.cv:
            self.assertTrue(h.worker.state.cv.wait_for(lambda: len(h.worker.state.queue) == 2, timeout=1))
            self.assertEqual(h.worker.state.mode, "REJOINING")
            self.assertIsNone(h.worker.state.current)
        self.assertFalse(any(m.kind in {"RESULT", "HB", "REQ"} for m in h.coord.quiet()))
        h.coord.send("WELCOME")
        h.launcher.receive("REJOINED")
        self.assertEqual([h.coord.receive("RESULT").fields for _ in range(2)],
                         [("0", "2", "9592"), ("152", "2", "6075")])
        self.assertEqual(h.logger.wait("TAKEOVER", task=0)["resume_step"], 6)
        h.coord.receive("REQ")
        h.coord.send("NO_TASK")
        self.assertEqual(sum(m.kind == "REQ" for m in h.coord.history), 2)

    def test_takeover_then_welcome_in_same_tcp_batch_is_not_lost(self):
        h = self.make()
        h.launcher.send("CRASH")
        h.logger.wait("CRASH", crash_count=1)
        h.launcher.send("RESTART")
        h.coord.receive("REJOIN")
        h.coord.send("TAKEOVER 152 2 from=4\nWELCOME")
        h.launcher.receive("REJOINED")
        self.assertEqual(h.coord.receive("RESULT").fields, ("152", "2", "6075"))

    def test_ready_waits_for_start(self):
        h = Harness()
        self.addCleanup(h.close)
        h.worker.start()
        h.coord = Wire(h.coord_listener.accept()[0])
        h.wires.append(h.coord)
        h.coord.receive("HELLO")
        h.connect_launcher()
        self.assertEqual(h.launcher.quiet(), [])
        self.assertFalse(h.worker.state.ready_sent)

    def test_ring_wrap_worker1_accepts_worker10_ckpt(self):
        h = self.make(worker_id=1)
        prev = h.predecessor()
        partial = sum(count_step(0, s) for s in range(1, 6))
        prev.send(f"CKPT 0 2 5 {partial}")
        h.logger.wait("CKPT", direction="receive", task=0)
        h.coord.send("NO_TASK\nTAKEOVER 0 3 from=10")
        self.assertEqual(h.coord.receive("RESULT").fields, ("0", "3", "9592"))
        self.assertEqual(h.logger.wait("TAKEOVER", task=0)["resume_step"], 6)

    def test_peer_failure_warns_and_keeps_computing(self):
        h = self.make()
        with h.worker.send_gate:
            h.worker.buddy.sock.close()
            h.worker.buddy = None
        h.coord.send("ASSIGN 0 1")
        self.assertEqual(h.coord.receive("RESULT").fields, ("0", "1", "9592"))
        self.assertTrue(any(event == "CKPT" and status == "WARN" for event, status, _ in h.logger.records))

    def test_stale_reply_logs_epoch_and_never_clears_new_assignment(self):
        h = self.make(delay=20)
        h.coord.send("ASSIGN 0 1")
        h.coord.receive("RESULT")
        h.coord.receive("REQ")
        h.coord.send("ASSIGN 152 1\nREJECT_STALE 0 DONE")
        self.assertEqual(h.logger.wait("REJECT_STALE", task=0)["epoch"], 1)
        self.assertEqual(h.coord.receive("RESULT").fields, ("152", "1", "6075"))

    def test_malformed_line_is_reported_and_coordinator_eof_is_fatal(self):
        h = self.make()
        h.coord.send("ASSIGN 1000 1\nNO_TASK")
        h.logger.wait("PROTOCOL", role="coordinator")
        h.logger.wait("NO_TASK")
        h.allow_failure = True
        h.coord.sock.shutdown(socket.SHUT_RDWR)
        self.assertTrue(h.worker.state.stop_event.wait(2))
        self.assertIsNotNone(h.worker.error)


class HeartbeatWaitTests(unittest.TestCase):
    def test_crashed_heartbeat_waits_on_cv_without_timeout_and_bye_wakes_it(self):
        worker = Worker(WorkerConfig(1, ("localhost", 4575), "127.0.0.1", 7001, 100, "test", "."), MemoryLogger())
        worker.state.start()
        worker.state.crash()
        entered = threading.Event()
        timeouts = []
        original_wait = worker.state.cv.wait
        def observed_wait(timeout=None):
            timeouts.append(timeout)
            entered.set()
            return original_wait(timeout)
        worker.state.cv.wait = observed_wait
        thread = threading.Thread(target=lambda: heartbeat_loop(worker))
        thread.start()
        try:
            self.assertTrue(entered.wait(1), "Heartbeat never entered Condition.wait while CRASHED")
            with worker.state.cv:
                self.assertEqual(timeouts, [None])
            self.assertEqual(worker.logger.records, [])
        finally:
            worker.handle_coordinator(Message("BYE", ()))
            thread.join(2)
        self.assertFalse(thread.is_alive())


class SendBoundaryTests(unittest.TestCase):
    def worker(self, sock):
        worker = Worker(WorkerConfig(1, ("localhost", 4575), "127.0.0.1", 7001, 100, "test", "."), MemoryLogger())
        worker.coordinator = Channel(sock)
        worker.state.start()
        return worker

    def test_old_sender_waiting_at_gate_is_suppressed_after_crash(self):
        class RecordingSocket:
            def __init__(self):
                self.messages = []
            def sendall(self, data):
                self.messages.append(data)
        sock = RecordingSocket()
        worker = self.worker(sock)
        result = []
        with worker.send_gate:
            thread = threading.Thread(target=lambda: result.append(worker.send_normal("HB", (1,), 0)))
            thread.start()
            worker.state.crash()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])
        self.assertEqual(sock.messages, [])

    def test_inflight_send_finishes_before_crash_transition_without_state_lock(self):
        class BlockingSocket:
            def __init__(self):
                self.entered = threading.Event()
                self.release = threading.Event()
            def sendall(self, data):
                self.entered.set()
                if not self.release.wait(2):
                    raise TimeoutError("test send timeout")
        sock = BlockingSocket()
        worker = self.worker(sock)
        sender = threading.Thread(target=lambda: worker.send_normal("HB", (1,), 0))
        crashed = threading.Event()
        def crash():
            worker.handle_launcher(Message("CRASH", ()))
            crashed.set()
        sender.start()
        self.assertTrue(sock.entered.wait(1))
        crasher = threading.Thread(target=crash)
        crasher.start()
        try:
            self.assertFalse(crashed.wait(0.05))
            for lock in (worker.state.queue_lock, worker.state.state_lock, worker.state.store_lock):
                self.assertTrue(lock.acquire(timeout=0.1), "business lock held during network I/O")
                lock.release()
        finally:
            sock.release.set()
            sender.join(2)
            crasher.join(2)
        self.assertTrue(crashed.is_set())
        self.assertEqual(worker.state.mode, "CRASHED")
        self.assertFalse(worker.send_normal("RESULT", (0, 1, 9592), 0))


class ConsecutiveBuddyTests(unittest.TestCase):
    def test_original_and_inherited_tasks_survive_two_adjacent_crashes(self):
        for ids in ((4, 5, 6), (10, 1, 2)):
            with self.subTest(ids=ids):
                server, last_buddy = listener(), listener()
                workers, coords, launchers, wires = [], [], [], []
                try:
                    for worker_id, delay in zip(ids, (50, 300, 100)):
                        reservation = listener()
                        port = reservation.getsockname()[1]
                        reservation.close()
                        worker = Worker(WorkerConfig(worker_id, server.getsockname(), "127.0.0.1", port,
                                                     delay, "consecutive-test", "."), MemoryLogger())
                        workers.append(worker)
                        worker.start()
                        coord = Wire(server.accept()[0])
                        coords.append(coord); wires.append(coord)
                        coord.receive("HELLO")
                    for index, worker in enumerate(workers):
                        port = workers[index + 1].config.peer_port if index < 2 else last_buddy.getsockname()[1]
                        coords[index].send(f"RING {ids[index] % 10 + 1} 127.0.0.1 {port}")
                        launch = Wire(socket.create_connection(worker.listener.getsockname(), timeout=1))
                        launchers.append(launch); wires.append(launch)
                        launch.send("LAUNCHER")
                    dummy = Wire(last_buddy.accept()[0]); wires.append(dummy)
                    dummy.receive("PEER")
                    for coord in coords:
                        coord.receive("RING_OK")
                        coord.send("START")
                    for launch, coord in zip(launchers, coords):
                        launch.receive("READY")
                        coord.receive("REQ")
                    coords[2].send("ASSIGN 271 1\nNO_TASK")
                    coords[1].send("ASSIGN 160 1\nNO_TASK")
                    coords[0].send("ASSIGN 152 1\nNO_TASK")
                    workers[1].logger.wait("CKPT", direction="receive", task=152, step=1)
                    launchers[0].send("CRASH")
                    workers[0].logger.wait("CRASH", crash_count=1)
                    coords[1].send(f"TAKEOVER 152 2 from={ids[0]}")
                    with workers[1].state.cv:
                        self.assertTrue(workers[1].state.cv.wait_for(
                            lambda: any(a.task == 152 for a in workers[1].state.queue), timeout=1))
                    workers[2].logger.wait("CKPT", direction="receive", task=160, step=1)
                    launchers[1].send("CRASH")
                    workers[1].logger.wait("CRASH", crash_count=1)
                    coords[2].send(f"TAKEOVER 152 3 from={ids[1]}\nTAKEOVER 160 2 from={ids[1]}")
                    results = [coords[2].receive("RESULT").fields for _ in range(3)]
                    self.assertEqual(results, [("271", "1", "5802"), ("152", "3", "6075"), ("160", "2", "5989")])
                    self.assertEqual(workers[2].logger.wait("TAKEOVER", task=152)["resume_step"], 1)
                    self.assertGreater(workers[2].logger.wait("TAKEOVER", task=160)["resume_step"], 1)
                    self.assertFalse(any(m.kind == "RESULT" for m in coords[0].quiet()))
                    self.assertFalse(any(m.kind == "RESULT" for m in coords[1].quiet()))
                finally:
                    for coord in coords:
                        try:
                            coord.send("BYE")
                        except OSError:
                            pass
                    for worker in workers:
                        worker.state.stop_event.wait(2)
                        worker.close()
                    for wire in wires:
                        wire.close()
                    server.close(); last_buddy.close()
                self.assertTrue(all(not worker.error for worker in workers))
                self.assertTrue(all(not t.is_alive() for w in workers for t in w.threads))


class ProcessTests(unittest.TestCase):
    def test_ten_worker_process_ring_completes_1000_tasks(self):
        server = listener()
        processes, coords, launchers, reservations = [], {}, {}, []
        with tempfile.TemporaryDirectory(prefix="hw3-ring-test-") as folder:
            try:
                reservations = [listener() for _ in range(10)]
                ports = [s.getsockname()[1] for s in reservations]
                for sock in reservations:
                    sock.close()
                for worker_id, port in enumerate(ports, 1):
                    processes.append(subprocess.Popen([
                        sys.executable, "-m", "hw3.worker",
                        "--id", str(worker_id), "--coord", f"127.0.0.1:{server.getsockname()[1]}",
                        "--peer-port", str(port), "--step-delay", "0", "--run-id", "ring-test", "--log-dir", folder,
                    ], cwd=Path(__file__).resolve().parents[2], stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                for _ in range(10):
                    coord = Wire(server.accept()[0])
                    hello = coord.receive("HELLO")
                    worker_id = int(hello.fields[0])
                    self.assertNotIn(worker_id, coords)
                    coords[worker_id] = coord
                for worker_id, coord in coords.items():
                    buddy_id = worker_id % 10 + 1
                    coord.send(f"RING {buddy_id} 127.0.0.1 {ports[buddy_id - 1]}")
                    launch = Wire(socket.create_connection(("127.0.0.1", ports[worker_id - 1]), timeout=1))
                    launchers[worker_id] = launch
                    launch.send("LAUNCHER")
                for coord in coords.values():
                    coord.receive("RING_OK", timeout=5)
                for coord in coords.values():
                    coord.send("START")
                for worker_id, launch in launchers.items():
                    self.assertEqual(launch.receive("READY").fields, (str(worker_id),))
                next_task, results = 0, {}
                no_task = set()
                deadline = time.monotonic() + 40
                with selectors.DefaultSelector() as selector:
                    for worker_id, coord in coords.items():
                        selector.register(coord.sock, selectors.EVENT_READ, worker_id)
                    while len(results) < 1000 or len(no_task) < 10:
                        self.assertLess(time.monotonic(), deadline, f"only {len(results)} results")
                        for key, _ in selector.select(0.1):
                            worker_id = key.data
                            coord = coords[worker_id]
                            coord.pump()
                            while coord.inbox:
                                message = coord.inbox.popleft()
                                if message.kind == "REQ":
                                    if next_task < 1000:
                                        coord.send(f"ASSIGN {next_task} 1")
                                        next_task += 1
                                    else:
                                        coord.send("NO_TASK")
                                        no_task.add(worker_id)
                                elif message.kind == "RESULT":
                                    task, epoch, value = map(int, message.fields)
                                    self.assertEqual(epoch, 1)
                                    self.assertNotIn(task, results, "duplicate RESULT")
                                    results[task] = value
                                    coord.send(f"ACK {task}")
                self.assertEqual(set(results), set(range(1000)))
                self.assertEqual(sum(results.values()), 5761455)
                for coord in coords.values():
                    coord.send("BYE")
                for process in processes:
                    out, err = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, (out, err))
                pids = set()
                for worker_id in range(1, 11):
                    lines = (Path(folder) / f"Worker{worker_id}.txt").read_text(encoding="utf-8").splitlines()
                    events = [(line.split(" | ")[1], json.loads(line.split(" | ")[-1])) for line in lines]
                    pids.add(next(record["pid"] for event, record in events if event == "INIT"))
                    self.assertTrue(any(event == "CKPT" and record["direction"] == "receive" for event, record in events))
                    self.assertEqual(next(record["threads_alive"] for event, record in events if event == "TERMINATE"), 0)
                self.assertEqual(len(pids), 10)
            finally:
                for coord in coords.values():
                    try:
                        coord.send("BYE")
                    except OSError:
                        pass
                for process in processes:
                    if process.poll() is None:
                        try:
                            process.communicate(timeout=4)
                        except subprocess.TimeoutExpired:
                            process.terminate()
                            process.communicate(timeout=4)
                for wire in (*coords.values(), *launchers.values()):
                    wire.close()
                for sock in reservations:
                    sock.close()
                server.close()

    def test_cli_subprocess_start_and_crashed_bye(self):
        coord_server, buddy_server = listener(), listener()
        process = None
        wires = []
        with tempfile.TemporaryDirectory(prefix="hw3-worker-test-") as folder:
            try:
                reservation = listener()
                peer_port = reservation.getsockname()[1]
                reservation.close()
                process = subprocess.Popen([sys.executable, "-m", "hw3.worker",
                                            "--id", "1", "--coord", f"127.0.0.1:{coord_server.getsockname()[1]}",
                                            "--peer-port", str(peer_port), "--step-delay", "10",
                                            "--run-id", "process-test", "--log-dir", folder],
                                           cwd=Path(__file__).resolve().parents[2],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                coord = Wire(coord_server.accept()[0]); wires.append(coord)
                self.assertEqual(coord.receive("HELLO").fields[0], "1")
                coord.send(f"RING 2 127.0.0.1 {buddy_server.getsockname()[1]}")
                buddy = Wire(buddy_server.accept()[0]); wires.append(buddy)
                buddy.receive("PEER")
                coord.receive("RING_OK")
                launcher = Wire(socket.create_connection(("127.0.0.1", peer_port), timeout=1)); wires.append(launcher)
                launcher.send("LAUNCHER")
                coord.send("START")
                launcher.receive("READY")
                coord.receive("REQ")
                coord.send("ASSIGN 0 1")
                self.assertEqual(coord.receive("RESULT").fields, ("0", "1", "9592"))
                launcher.send("CRASH")
                deadline = time.monotonic() + 2
                log = Path(folder) / "Worker1.txt"
                while time.monotonic() < deadline and " | CRASH | " not in log.read_text(encoding="utf-8"):
                    threading.Event().wait(0.02)
                self.assertIn(" | CRASH | ", log.read_text(encoding="utf-8"))
                coord.send("BYE")
                out, err = process.communicate(timeout=4)
                self.assertEqual(process.returncode, 0, (out, err))
                lines = log.read_text(encoding="utf-8").splitlines()
                termination = json.loads(next(line for line in lines if " | TERMINATE | " in line).split(" | ")[-1])
                self.assertEqual(termination["threads_alive"], 0)
                self.assertEqual(termination["run_id"], "process-test")
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=4)
                for wire in wires:
                    wire.close()
                coord_server.close(); buddy_server.close()


if __name__ == "__main__":
    unittest.main()
