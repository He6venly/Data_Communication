import socket
from threading import Event, Lock, Thread
from time import monotonic

from src.common.transport import Conn
from .deadline import DeadlineSocket
from .tracker_link import ProtocolError


def read_chunk(conn, idx, size):
    """DATA의 번호와 길이가 요청과 맞을 때만 본문을 읽음."""
    header = conn.read_line()
    if header in ("ERR NOCHUNK", "ERR NOFILE"):
        raise ProtocolError(header)
    if header.split() != ["DATA", str(idx), str(size)]:
        raise ProtocolError("invalid DATA header")
    return conn.read_exact(size)


class DownLimiter:
    """모든 worker가 같은 DOWN 전송 시간을 예약해 씀."""

    def __init__(self, kbps):
        self.rate = kbps * 1024
        self.lock = Lock()
        self.next_at = 0.0

    def take(self, size, cancelled):
        """실제 청크 길이만큼 시간이 지나야 GET을 보낼 수 있음."""
        with self.lock:
            self.next_at = max(monotonic(), self.next_at) + size / self.rate
            delay = self.next_at - monotonic()
        return not cancelled.wait(max(0, delay))


class DownloadPool:
    """worker마다 상대 소켓을 보관하고 오프라인 전환 때 깨워줌."""

    def __init__(self, config, peer, store, selection, emit, stopping, failed):
        self.count = config["download"]["workers"]
        self.ban_sec = config["timing"]["ban_sec"]
        self.store, self.selection, self.emit = store, selection, emit
        self.stopping, self.failed = stopping, failed
        self.limiter = DownLimiter(peer["down_kbps"])
        self.lock = Lock()
        self.cancelled = Event()
        self.cancelled.set()
        self.connections = {}
        self.threads = []

    def start(self):
        """설정된 개수의 다운로드 worker를 시작함."""
        for idx in range(self.count):
            thread = Thread(target=self.worker, args=(idx,), name=f"peer-download-{idx}")
            thread.start()
            self.threads.append(thread)

    def enable(self):
        """새 다운로드 요청에 사용할 취소 신호를 바꿈."""
        with self.lock:
            self.cancelled = Event()

    def disable(self):
        """새 송신을 막고 진행 중인 다운로드 소켓을 닫음."""
        with self.lock:
            self.cancelled.set()
            for _, conn in self.connections.values():
                conn.close()
            self.connections.clear()

    def cancel(self):
        """새 요청과 제한기 대기를 먼저 멈춤."""
        with self.lock:
            self.cancelled.set()

    def _connection(self, key, address, cancelled):
        """소켓을 추적 목록에 넣은 뒤 연결해 종료 요청에서 닫을 수 있게 함."""
        with self.lock:
            if cancelled.is_set():
                return None
            existing = self.connections.get(key)
            if existing is not None and existing[0] == address:
                return existing[1]
            if existing:
                existing[1].close()
            sock = socket.socket()
            sock.settimeout(5)
            conn = Conn(DeadlineSocket(sock))
            self.connections[key] = address, conn
        sock.connect(address)
        return conn

    def _drop(self, key, cancelled):
        with self.lock:
            if cancelled is self.cancelled:
                entry = self.connections.pop(key, None)
                if entry:
                    entry[1].close()

    def worker(self, idx):
        """청크를 받아 저장하고 성공 여부와 관계없이 예약을 반납함."""
        try:
            while not self.stopping.is_set():
                cancelled = self.cancelled
                task = None if cancelled.is_set() else self.selection.choose(self.store)
                if task is None:
                    self.stopping.wait(0.035)
                    continue
                token, pid, address, size = task
                key = idx, pid
                result = None
                try:
                    if not self.limiter.take(size, cancelled):
                        continue
                    conn = self._connection(key, address, cancelled)
                    if conn is None:
                        continue
                    if cancelled.is_set():
                        continue
                    conn.sock.deadline = monotonic()+5.0
                    conn.send_line(f"GET {token.file} {token.idx}")
                    data = read_chunk(conn, token.idx, size)
                except (OSError, ValueError) as exc:
                    self._drop(key, cancelled)
                    if not cancelled.is_set() and not self.stopping.is_set():
                        result = "fail"
                        self.emit("FAIL", file=token.file, idx=token.idx, src=pid, err=str(exc))
                else:
                    if not cancelled.is_set():
                        commit = self.store.commit(token, data, pid)
                        if commit.accepted:
                            result = "ok"
                finally:
                    self.store.release(token)
                    if self.selection.finish(token.file, pid, result):
                        self.emit("BAN", target=pid, sec=self.ban_sec)
        except Exception as exc:
            self.failed(exc)
