# Coordinator·Buddy·Launcher와 TCP로 통신한다.

from dataclasses import dataclass, field
import selectors
import socket
import threading
import time

from hw3.common.protocol import Message, ProtocolError, encode, parse
from hw3.common.transport import LineBuffer, send_line

from .compute import compute_loop
from .heartbeat import heartbeat_loop
from .state import Assignment, Checkpoint, WorkerState


@dataclass(frozen=True)
class WorkerConfig:
    worker_id: int
    coordinator: tuple[str, int]
    peer_ip: str
    peer_port: int
    step_delay_ms: int
    run_id: str
    log_dir: str


@dataclass(eq=False)
class Channel:
    sock: socket.socket
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    buffer: LineBuffer = field(default_factory=LineBuffer)
    role: str | None = None


class Worker:
    def __init__(self, config: WorkerConfig, logger):
        self.config = config
        self.logger = logger
        self.state = WorkerState()
        self.send_gate = threading.Lock()
        self.coordinator: Channel | None = None
        self.launcher: Channel | None = None
        self.buddy: Channel | None = None
        self.buddy_target: tuple[str, int] | None = None
        self.ring_ack_sent = False
        self.listener: socket.socket | None = None
        self.threads: list[threading.Thread] = []
        self.error: str | None = None

    def emit(self, event, status="INFO", **fields):
        self.logger.write(event, status, {"worker": self.config.worker_id, **fields})

    def _write(self, channel, kind, fields=()):
        if channel is None:
            raise ConnectionError(f"{kind}: missing connection")
        send_line(channel.sock, encode(Message(kind, tuple(str(f) for f in fields))), channel.send_lock)

    def fail(self, error):
        self.error = str(error)
        self.state.stop()
        self.emit("ERROR", "FAIL", error=self.error)

    def stop(self):
        with self.send_gate:
            self.state.stop()

    def send_normal(self, kind, fields, generation, *, assignment=None, target="coordinator"):
        try:
            with self.send_gate:
                with self.state.locked():
                    allowed = self.state.active(generation, assignment)
                if not allowed:
                    return False
                self._write(getattr(self, target), kind, fields)
                if kind == "RESULT":
                    with self.state.locked():
                        self.state.sent_epochs.setdefault(int(fields[0]), set()).add(int(fields[1]))
                return True
        except (OSError, ValueError) as error:
            self.fail(error)
            return False

    def request_if_idle(self):
        try:
            with self.send_gate:
                with self.state.locked():
                    if not self.state.needs_request():
                        return False
                    self.state.requested = True
                self._write(self.coordinator, "REQ", (self.config.worker_id,))
            self.emit("REQ")
            return True
        except (OSError, ValueError) as error:
            self.fail(error)
            return False

    def send_rejoin_if_due(self):
        try:
            with self.send_gate:
                with self.state.locked():
                    due = self.state.rejoin_due
                    if self.state.mode != "REJOINING" or due is None or time.monotonic() < due:
                        return False
                    self.state.rejoin_due = None
                    rejoin_count = self.state.rejoin_count + 1
                self._write(self.coordinator, "REJOIN", (self.config.worker_id,))
            self.emit("REJOIN", rejoin_count=rejoin_count)
            return True
        except (OSError, ValueError) as error:
            self.fail(error)
            return False

    def send_ready(self):
        try:
            with self.send_gate:
                with self.state.locked():
                    if (self.state.mode != "RUNNING" or not self.state.started
                            or not self.state.launcher_connected or self.state.ready_sent):
                        return False
                self._write(self.launcher, "READY", (self.config.worker_id,))
                with self.state.locked():
                    self.state.ready_sent = True
            self.emit("READY")
            return True
        except (OSError, ValueError) as error:
            self.fail(error)
            return False

    def send_checkpoint(self, work, step, partial):
        try:
            with self.send_gate:
                with self.state.locked():
                    allowed = self.state.active(work.generation, work.assignment)
                if not allowed:
                    return False
                self._write(self.buddy, "CKPT", (work.assignment.task, work.assignment.epoch, step, partial))
            self.emit("CKPT", task=work.assignment.task, epoch=work.assignment.epoch,
                      step=step, partial=partial, direction="send", buddy=self.config.worker_id % 10 + 1)
            return True
        except (OSError, ValueError) as error:
            with self.send_gate:
                if self.buddy is not None:
                    self.buddy.sock.close()
                    self.buddy = None
            self.emit("CKPT", "WARN", task=work.assignment.task, epoch=work.assignment.epoch,
                      step=step, partial=partial, direction="send", error=str(error))
            return False

    def handle_coordinator(self, message):
        kind, fields = message.kind, message.fields
        if kind == "BYE":
            self.emit("BYE")
            self.stop()
            return
        with self.state.locked():
            mode, generation = self.state.mode, self.state.crash_gen
        if mode in {"CRASHED", "STOPPED"}:
            return
        if kind == "RING" and mode == "BOOTING":
            buddy, ip, port = fields
            if int(buddy) != self.config.worker_id % 10 + 1:
                raise ProtocolError("RING does not name the fixed Buddy")
            with self.send_gate:
                self.buddy_target = (ip, int(port))
            self.emit("RING", buddy=int(buddy), ip=ip, port=int(port))
        elif kind == "START" and self.state.start():
            self.emit("START", ring_ready=self.ring_ack_sent, started_at_unix_ms=int(time.time() * 1000))
            self.send_ready()
        elif ((kind == "ASSIGN" and mode == "RUNNING")
              or (kind == "TAKEOVER" and mode in {"RUNNING", "REJOINING"})):
            task, epoch = map(int, fields[:2])
            source = int(fields[2].split("=", 1)[1]) if kind == "TAKEOVER" else None
            if self.state.enqueue(Assignment(task, epoch, source), generation) and kind == "ASSIGN":
                self.emit("ASSIGN", task=task, epoch=epoch)
        elif kind == "NO_TASK":
            if self.state.mark_no_task(generation):
                self.emit("NO_TASK")
        elif kind == "WELCOME" and self.state.welcome():
            with self.state.locked():
                generation, count = self.state.crash_gen, self.state.rejoin_count
            self.emit("WELCOME", rejoin_count=count)
            if self.send_normal("REJOINED", (self.config.worker_id,), generation, target="launcher"):
                self.emit("REJOINED", rejoin_count=count)
        elif kind == "RETRY_LATER":
            if self.state.retry_later():
                self.emit("RETRY_LATER")
        elif kind == "ACK" and mode == "RUNNING":
            self.emit("ACK", task=int(fields[0]))
        elif kind == "REJECT_STALE" and mode == "RUNNING":
            task = int(fields[0])
            with self.send_gate:
                with self.state.locked():
                    if self.state.mode != "RUNNING":
                        return
                    epochs = self.state.sent_epochs.get(task, set())
                    epoch = next(iter(epochs)) if len(epochs) == 1 and self.state.crash_gen == 0 else None
            self.emit("REJECT_STALE", "WARN", task=task, epoch=epoch, reason=fields[1])

    def handle_launcher(self, message):
        if message.kind == "CRASH":
            with self.send_gate:
                cleared = self.state.crash()
            if cleared is not None:
                self.emit("CRASH", **cleared)
        elif message.kind == "RESTART":
            with self.send_gate:
                restarted = self.state.restart()
            if restarted:
                self.emit("RESTART")
                self.send_rejoin_if_due()
        else:
            raise ProtocolError("unexpected Launcher message")

    def handle_incoming(self, channel, message):
        if channel.role is None:
            if message.kind == "LAUNCHER":
                with self.send_gate:
                    if self.launcher is not None:
                        raise ProtocolError("duplicate Launcher connection")
                    self.launcher = channel
                    channel.role = "launcher"
                    with self.state.locked():
                        self.state.launcher_connected = True
                self.emit("CONNECT", role="launcher")
                self.send_ready()
            elif (message.kind == "PEER"
                  and int(message.fields[0]) == (self.config.worker_id - 2) % 10 + 1):
                channel.role = "peer"
                self.emit("CONNECT", role="peer", peer=int(message.fields[0]))
            else:
                raise ProtocolError("connection must identify LAUNCHER or predecessor PEER")
        elif channel.role == "launcher":
            self.handle_launcher(message)
        elif message.kind == "CKPT":
            task, epoch, step, partial = map(int, message.fields)
            if self.state.save_checkpoint(task, Checkpoint(epoch, step, partial)):
                self.emit("CKPT", task=task, epoch=epoch, step=step, partial=partial, direction="receive")
        else:
            raise ProtocolError("unexpected Peer message")

    def control_loop(self):
        try:
            while not self.state.stop_event.is_set():
                try:
                    data = self.coordinator.sock.recv(65_536)
                except socket.timeout:
                    continue
                if not data:
                    raise ConnectionError("Coordinator EOF")
                for line in self.coordinator.buffer.feed(data):
                    try:
                        self.handle_coordinator(parse(line))
                    except ProtocolError as error:
                        self.emit("PROTOCOL", "WARN", role="coordinator", error=str(error))
                    if self.state.stop_event.is_set():
                        break
        except (OSError, ValueError) as error:
            if not self.state.stop_event.is_set():
                self.fail(error)

    def connect_buddy(self):
        with self.send_gate:
            with self.state.locked():
                if self.state.mode in {"CRASHED", "STOPPED"}:
                    return
            if self.buddy is not None or self.buddy_target is None:
                return
            target = self.buddy_target
        channel = None
        try:
            channel = Channel(socket.create_connection(target, timeout=0.5), role="buddy")
            channel.sock.settimeout(1.0)
            with self.send_gate:
                with self.state.locked():
                    allowed = self.state.mode in {"BOOTING", "RUNNING", "REJOINING"}
                if not allowed:
                    channel.sock.close()
                    return
                self._write(channel, "PEER", (self.config.worker_id,))
                self.buddy = channel
                if not self.ring_ack_sent:
                    self._write(self.coordinator, "RING_OK", (self.config.worker_id,))
                    self.ring_ack_sent = True
            self.emit("CONNECT", role="buddy", buddy=self.config.worker_id % 10 + 1,
                      ip=target[0], port=target[1])
        except OSError as error:
            if channel is not None:
                channel.sock.close()
                with self.send_gate:
                    if self.buddy is channel:
                        self.buddy = None
                        self.fail(error)
            self.emit("CONNECT", "WARN", role="buddy", error=str(error))

    def peer_loop(self):
        next_connect = 0.0
        with selectors.DefaultSelector() as selector:
            selector.register(self.listener, selectors.EVENT_READ, None)
            try:
                while not self.state.stop_event.is_set():
                    if time.monotonic() >= next_connect:
                        self.connect_buddy()
                        next_connect = time.monotonic() + 0.5
                    for key, _ in selector.select(0.1):
                        if key.data is None:
                            sock, _ = self.listener.accept()
                            sock.settimeout(1.0)
                            channel = Channel(sock)
                            selector.register(sock, selectors.EVENT_READ, channel)
                            continue
                        channel = key.data
                        try:
                            data = channel.sock.recv(65_536)
                            if not data:
                                raise ConnectionError("EOF")
                            for line in channel.buffer.feed(data):
                                self.handle_incoming(channel, parse(line))
                        except (OSError, ValueError) as error:
                            selector.unregister(channel.sock)
                            channel.sock.close()
                            if channel is self.launcher:
                                if not self.state.stop_event.is_set():
                                    self.fail(f"Launcher connection: {error}")
                            else:
                                self.emit("CONNECT", "WARN", role=channel.role or "unknown", error=str(error))
            except OSError as error:
                if not self.state.stop_event.is_set():
                    self.fail(error)
            finally:
                for key in list(selector.get_map().values()):
                    if key.data is not None:
                        key.fileobj.close()

    def _thread(self, target):
        try:
            target()
        except Exception as error:
            self.fail(f"{threading.current_thread().name}: {error}")

    def start(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind((self.config.peer_ip, self.config.peer_port))
        self.listener.listen(16)
        self.listener.settimeout(1.0)
        while not self.state.stop_event.is_set():
            try:
                sock = socket.create_connection(self.config.coordinator, timeout=1.0)
                sock.settimeout(1.0)
                self.coordinator = Channel(sock, role="coordinator")
                break
            except ConnectionRefusedError:
                self.state.stop_event.wait(0.5)
        if self.coordinator is None:
            return
        self.emit("CONNECT", role="coordinator", host=self.config.coordinator[0], port=self.config.coordinator[1])
        with self.send_gate:
            self._write(self.coordinator, "HELLO",
                        (self.config.worker_id, self.config.peer_ip, self.config.peer_port))
        for name, target in (("Control Recv", self.control_loop), ("Peer Server", self.peer_loop),
                             ("Compute", lambda: compute_loop(self)),
                             ("Heartbeat", lambda: heartbeat_loop(self))):
            thread = threading.Thread(name=f"Worker{self.config.worker_id} {name}",
                                      target=self._thread, args=(target,))
            self.threads.append(thread)
            thread.start()

    def close(self):
        self.stop()
        for channel in (self.coordinator, self.buddy, self.launcher):
            if channel is not None:
                try:
                    channel.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        for thread in self.threads:
            thread.join()
        for channel in (self.coordinator, self.buddy, self.launcher):
            if channel is not None:
                channel.sock.close()
        if self.listener is not None:
            self.listener.close()
        self.emit("TERMINATE", "FAIL" if self.error else "SUCCESS", error=self.error,
                  threads_alive=sum(thread.is_alive() for thread in self.threads))
        self.logger.close()
