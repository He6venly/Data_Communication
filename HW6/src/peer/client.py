import socket
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import monotonic

from src.common.contracts import ConfigurationError, PeerView, ShutdownError, StoreIOError
from src.common.transport import Conn
from .control import Control
from .deadline import DeadlineSocket
from .download import DownloadPool
from .selection import Selection
from .tracker_link import ProtocolError, TrackerLink


def read_bitmap(address, name, count, timeout):
    """상대 bitmap의 청크 수와 각 비트를 확인해서 돌려줌."""
    conn = None
    deadline = monotonic()+timeout
    try:
        conn = Conn(DeadlineSocket(socket.create_connection(address, timeout=timeout)))
        conn.sock.deadline = deadline
        conn.send_line(f"BITMAP {name}")
        head = conn.read_line().split()
        if (len(head) == 3 and head[:2] == ["BITMAP", str(count)]
                and len(head[2]) == count and not set(head[2]) - {"0", "1"}):
            return head[2]
    except (OSError, ValueError):
        pass
    finally:
        if conn is not None:
            conn.close()
    return None


class Peer:
    """시작·가상 장애·종료를 main에서 조율함."""

    def __init__(self, args, env, peer, store, upload, screen, log, stopping, started_at):
        self.args, self.env, self.peer = args, env, peer
        self.store, self.upload, self.screen, self.log = store, upload, screen, log
        self.stopping, self.started_at = stopping, started_at
        self.rng_seed = env["download"]["policy_seed"] + int(peer["id"][1:])
        self.selection = Selection(env, args.policy, self.rng_seed)
        self.link = TrackerLink((args.host, args.port), peer["id"], len(env["files"]), len(env["peers"]))
        self.control = Control(env, peer, self.link, store, self.selection, read_bitmap, log.event)
        self.control.started_at = started_at
        self.outcomes = Queue()
        self.pool = DownloadPool(env, peer, store, self.selection, log.event, stopping,
                                 lambda error: self.outcomes.put(error))
        self.control_thread = None
        self.online = False
        self.initialized = self.upload_started = self.screen_started = False
        self.joined = False
        self.view_lock = Lock()
        self.view_prev = None
        self.interrupted = Event()

    def view(self):
        """화면용 복사본과 직전 조회 이후의 실제 속도를 계산함."""
        with self.view_lock:
            snap = self.store.snapshot()
            now = monotonic()
            before = self.view_prev or (self.started_at, 0, 0)
            elapsed = max(now-before[0], 1e-9)
            self.view_prev = (now, snap.sent_bytes, snap.received_bytes)
            return PeerView(peer_id=self.peer["id"], elapsed_sec=now-self.started_at,
                            online=self.online, policy=self.args.policy,
                            up_kbps=self.peer["up_kbps"], down_kbps=self.peer["down_kbps"],
                            actual_up_kbps=(snap.sent_bytes-before[1])/elapsed/1024,
                            actual_down_kbps=(snap.received_bytes-before[2])/elapsed/1024,
                            files=snap.files)

    def _control_loop(self, recovering):
        """Tracker 갱신을 진행하고 복귀가 끝난 뒤 worker를 열어줌."""
        control = self.control
        pending_start = True
        lost_sec = self.env["timing"]["tracker_lost_sec"]
        control.last_ok = monotonic()
        try:
            while not self.stopping.is_set() and not self.interrupted.is_set():
                now = monotonic()
                silent = now-control.last_ok
                if silent >= lost_sec:
                    self.outcomes.put(("abort", "tracker_lost", silent))
                    return
                self.link.max_timeout = min(5.0, max(0.001, lost_sec-silent))
                try:
                    snap = self.store.snapshot()
                    if now >= control.next_heartbeat:
                        command = control.heartbeat(snap)
                        self.joined = True
                        control.next_heartbeat = now+self.env["timing"]["heartbeat_sec"]
                        if command:
                            self.outcomes.put(command)
                            return
                    report_due = now >= control.next_report
                    if report_due:
                        for f in snap.files:
                            control.ok(f"REPORT {self.peer['id']} {f.name} {f.sent} {f.distinct} {f.bitmap}")
                        head, _ = control.request("STATE")
                        parts = head.split(maxsplit=4)
                        if (len(parts) not in (4, 5) or parts[0] != "STATE"
                                or not all(p.isascii() and p.isdigit() for p in parts[1:3])
                                or (len(parts) == 4 and parts[3] not in ("WAIT", "ALLDONE"))
                                or (len(parts) == 5 and parts[3] != "ABORT")):
                            raise ProtocolError("invalid STATE response")
                        if parts[3] == "ALLDONE":
                            self.outcomes.put(("all", int(parts[1]), int(parts[2])))
                            return
                        if parts[3] == "ABORT":
                            self.outcomes.put(("abort", parts[4], 0))
                            return
                        control.next_report = now+1
                    ready = control.sync_registration(snap.files)
                    control.refresh(self.store.snapshot().files, now, force=pending_start and ready)
                    if ready and pending_start and not self.stopping.is_set() and not self.interrupted.is_set():
                        self.outcomes.put(("ready", recovering))
                        pending_start = False
                    if ready and report_due:
                        control.update_done(self.store.snapshot().files, now)
                except OSError:
                    pass
                self.stopping.wait(0.05 if pending_start else 0.08)
        except Exception as exc:
            self.outcomes.put(exc)

    def _start_control(self, recovering=False):
        self.control_thread = Thread(target=self._control_loop, args=(recovering,), name="peer-control")
        self.control_thread.start()

    def _join(self, thread):
        if thread is not None:
            thread.join(6)
            if thread.is_alive():
                raise ShutdownError(f"{thread.name} did not stop", operation="join")

    def _active(self):
        """제어 스레드의 지시를 받아 장애와 종료 순서를 적용함."""
        self.store.initialize()
        self.initialized = True
        self.upload.start()
        self.upload_started = True
        self.online = True
        self._start_control()
        while not self.interrupted.is_set():
            try:
                outcome = self.outcomes.get(timeout=0.1)
            except Empty:
                continue
            if isinstance(outcome, Exception):
                raise outcome
            kind, *fields = outcome
            if kind == "ready":
                self.online = True
                if not self.screen_started:
                    self.screen.start(snapshot=self.view, recent=self.log.recent)
                    self.screen_started = True
                    self.pool.start()
                if fields[0]:
                    self.log.event("REJOIN")
                self.pool.enable()
                continue
            if kind == "all":
                self.log.event("ALLDONE", done=fields[0], alive=fields[1])
                return 0
            if kind == "abort":
                self.log.event("ABORT", reason=fields[0], silent_sec=fields[1])
                return 2
            if kind == "destroy":
                self.online = False
                self.pool.cancel()
                self.log.event("DESTROY")
                return 3
            self._join(self.control_thread)
            self.online = False
            self.pool.cancel()
            self.store.pause()
            self.upload.offline()
            self.pool.disable()
            self.link.close()
            self.log.event("CRASH", sec=fields[0])
            if self.interrupted.wait(fields[0]):
                break
            self.store.resume()
            self.upload.online()
            self.control.reset()
            self._start_control(recovering=True)
        self.log.event("ABORT", reason="interrupted", silent_sec=0)
        return 2

    def _error(self, exc):
        if isinstance(exc, ConfigurationError):
            kind = "config"
        elif isinstance(exc, ShutdownError):
            kind = "shutdown"
        elif isinstance(exc, (StoreIOError, OSError)):
            kind = "local_io"
        else:
            kind = "contract"
        self.log.event("ERROR", kind=kind, operation=getattr(exc, "operation", ""),
                       file=getattr(exc, "file", None), message=str(exc))

    def run(self):
        """업로드·worker·control을 정리한 뒤 결과와 마지막 EXIT를 기록함."""
        self.log.event("START", env=str(self.args.env), policy=self.args.policy,
                       up_kbps=self.peer["up_kbps"], down_kbps=self.peer["down_kbps"],
                       run=self.env["run"], seed=self.env["seed"], description=self.env["description"],
                       rng_seed=self.rng_seed, tracker=f"{self.args.host}:{self.args.port}")
        code = 2
        try:
            code = self._active()
        except KeyboardInterrupt:
            self.interrupted.set()
        except Exception as exc:
            self._error(exc)
            code = 1 if isinstance(exc, ConfigurationError) else 2
        self.online = False
        self.stopping.set()
        self.pool.disable()
        if self.control_thread is not None and self.control_thread.is_alive():
            self.link.close()
        snap = None
        safe = True
        if self.upload_started:
            try:
                self.upload.stop(0.0 if code == 3 else 3.0)
            except Exception as exc:
                self._error(exc)
                safe, code = False, 2
        try:
            for thread in [*self.pool.threads, self.control_thread]:
                self._join(thread)
            if safe and self.initialized:
                snap = self.store.finalize()
            if self.joined and code != 3 and safe:
                try:
                    self.link.max_timeout = 1.0
                    self.link.request(f"BYE {self.peer['id']}", timeout=1)
                except (OSError, ValueError):
                    pass
        except Exception as exc:
            self._error(exc)
            code = 2
        finally:
            self.link.close()
            if self.screen_started:
                try:
                    self.screen.stop()
                except Exception as exc:
                    self._error(exc)
                    code = 2
        self.log.event("EXIT", code=code, up_mb=(snap.sent_bytes if snap else 0)/2**20,
                       down_mb=(snap.received_bytes if snap else 0)/2**20)
        return code
