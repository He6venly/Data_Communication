import math
from time import monotonic

from src.common.contracts import FileState
from .tracker_link import ProtocolError


class Control:
    """등록과 주기 제어를 한 곳에서 처리하고 다운로드 상태를 판단함."""

    def __init__(self, env, peer, link, store, selection, bitmap, emit):
        self.env, self.peer, self.link, self.store = env, peer, link, store
        self.selection, self.bitmap, self.emit = selection, bitmap, emit
        self.pid = peer["id"]
        self.expected = {f["name"]: (f["size"], env["chunk_size"],
                         (f["size"]+env["chunk_size"]-1)//env["chunk_size"]) for f in env["files"]}
        self.endpoints = {p["id"]: (p["host"], p["port"]) for p in env["peers"]}
        self.registered = set()
        self.complete_logged = set()
        self.prepared_logged = set()
        self.have = set()
        self.holders = {}
        self.zero_since = {}
        self.done = None
        self.last_ok = monotonic()
        self.next_heartbeat = self.next_report = self.next_peers = self.next_bitmap = 0
        self.cursor = 0
        self.peer_cursor = 0
        self.started_at = monotonic()

    def request(self, message, timeout=5.0):
        head, rows = self.link.request(message, timeout)
        self.last_ok = monotonic()
        return head, rows

    def ok(self, message):
        if self.request(message) != ("OK", ()):
            raise ProtocolError(f"Tracker rejected {message.split()[0]}")

    def reset(self):
        """복귀 시 재등록과 캐시 갱신을 처음부터 수행함."""
        self.registered.clear()
        self.have.clear()
        self.holders.clear()
        self.zero_since.clear()
        self.selection.clear()
        self.next_heartbeat = self.next_report = self.next_peers = self.next_bitmap = 0
        self.last_ok = monotonic()

    def sync_registration(self, files):
        """검증이 끝난 파일을 먼저 등록하고 목록이 갖춰지면 부분 보유도 알림."""
        for f in files:
            if f.state == FileState.SEED and f.name not in self.registered:
                self.ok(f"REGISTER {self.pid} {self.peer['port']} {f.name} {f.size} {f.chunk_size}")
                self.registered.add(f.name)
                if f.origin != self.pid and f.name not in self.complete_logged:
                    self.emit("COMPLETE", file=f.name, sec=monotonic()-self.started_at, sources=dict(f.sources))
                    self.complete_logged.add(f.name)
        missing = [f for f in files if f.state != FileState.SEED and f.name not in self.have]
        if not missing:
            return True
        head, rows = self.request("LIST")
        if not head.startswith("FILES "):
            raise ProtocolError("LIST did not return FILES")
        names = set()
        for row in rows:
            name, size, chunk, count, holders = row.split()
            if name in names or self.expected.get(name) != (int(size), int(chunk), int(count)) or int(holders) < 1:
                raise ProtocolError("LIST metadata mismatch")
            names.add(name)
        if names != self.expected.keys():
            return False
        for f in missing:
            if not f.prepared:
                self.store.prepare_download(f.name)
            if f.name not in self.prepared_logged:
                self.emit("GET", file=f.name, chunks=f.nchunks)
                self.prepared_logged.add(f.name)
            response, _ = self.request(f"HAVE {self.pid} {self.peer['port']} {f.name}")
            if response == "ERR NOFILE":
                return False
            if response != "OK":
                raise ProtocolError("HAVE rejected")
            self.have.add(f.name)
        return True

    def refresh(self, files, now, force=False):
        """전체 시간 예산 안에서 명단과 원격 bitmap을 순서대로 갱신함."""
        targets = {f.name: f for f in files if f.name in self.have and f.state in (FileState.DOWN, FileState.STALLED)}
        if force or now >= self.next_peers:
            deadline = monotonic()+0.35
            names = list(targets)
            for _ in names:
                remaining = deadline-monotonic()
                if remaining <= 0:
                    break
                name = names[self.peer_cursor % len(names)]
                self.peer_cursor += 1
                head, rows = self.request(f"PEERS {name}", remaining)
                if head != "ERR NOFILE" and not head.startswith("PEERS "):
                    raise ProtocolError("invalid PEERS response")
                peers = set()
                for row in rows:
                    pid, host, port = row.split()
                    if pid in peers or self.endpoints.get(pid) != (host, int(port)):
                        raise ProtocolError("PEERS endpoint mismatch")
                    peers.add(pid)
                self.holders[name] = peers - {self.pid}
            self.next_peers = now+self.env["timing"]["peers_refresh_sec"]
        keys = sorted((name, pid) for name in targets for pid in self.holders.get(name, ()))
        self.selection.prune(set(keys))
        if keys and (force or now >= self.next_bitmap):
            deadline = monotonic()+0.35
            for offset in range(len(keys)):
                remaining = deadline-monotonic()
                if remaining <= 0:
                    break
                name, pid = keys[self.cursor % len(keys)]
                self.cursor += 1
                address = self.endpoints[pid]
                bits = self.bitmap(address, name, targets[name].nchunks, min(0.12, remaining))
                self.selection.update(name, pid, address, bits)
            self.next_bitmap = now+self.env["timing"]["bitmap_refresh_sec"]

    def heartbeat(self, snap):
        """생존 신호를 보내고 응답의 장애 지시만 받아들임."""
        head, _ = self.request(f"HEARTBEAT {self.pid} {snap.downloaded_have}")
        fields = head.split()
        if head == "OK":
            return None
        if fields == ["CMD", "DESTROY"]:
            return "destroy", 0
        if len(fields) == 3 and fields[:2] == ["CMD", "DISCONNECT"]:
            delay = float(fields[2])
            if math.isfinite(delay) and delay > 0:
                return "crash", delay
        raise ProtocolError("invalid HEARTBEAT response")

    def update_done(self, files, now):
        """유실이 지속된 파일만 STALLED로 바꾸고 DONE 상태를 맞춤."""
        for f in files:
            if f.state not in (FileState.DOWN, FileState.STALLED):
                self.zero_since.pop(f.name, None)
                continue
            if self.selection.has_source(f):
                self.zero_since.pop(f.name, None)
                if self.store.set_stalled(f.name, False):
                    self.emit("UNSTALLED", file=f.name)
            elif (f.prepared and not f.in_progress and "0" in f.bitmap
                  and now-self.zero_since.setdefault(f.name, now) >= self.env["timing"]["stall_sec"]):
                if self.store.set_stalled(f.name, True):
                    self.emit("STALLED", file=f.name, lost=f.bitmap.count("0"))
            elif f.in_progress or "0" not in f.bitmap:
                self.zero_since.pop(f.name, None)
        detail = []
        ready = True
        for f in self.store.snapshot().files:
            if f.state == FileState.FAILED:
                detail.append(f"{f.name}:FAILED")
            elif f.state == FileState.STALLED:
                detail.append(f"{f.name}:{f.bitmap.count('0')}")
            elif f.state != FileState.SEED or f.name not in self.registered:
                ready = False
        target = ("PARTIAL", " ".join(detail)) if detail else ("FULL", "")
        if self.done is not None and (not ready or self.done != target):
            self.ok(f"UNDONE {self.pid}")
            self.done = None
            self.emit("UNDONE")
        if ready and self.done != target:
            self.ok(f"DONE {self.pid} {target[0]} {target[1]}".rstrip())
            self.done = target
            self.emit("DONE", kind=target[0], detail=target[1])
