from collections import Counter
from random import Random
from threading import Lock
from time import monotonic

from src.common.contracts import FileState


class Selection:
    """원격 보유 상태·피어별 요청 수·실패 기록으로 다음 요청을 정함."""

    def __init__(self, env, policy, seed):
        self.lock = Lock()
        self.policy = policy
        self.rng = Random(seed)
        self.limit = env["download"]["per_peer_max"]
        self.fail_limit = env["timing"]["fail_limit"]
        self.ban_sec = env["timing"]["ban_sec"]
        self.order = [(f["name"], i) for f in env["files"]
                      for i in range((f["size"] + env["chunk_size"]-1)//env["chunk_size"])]
        if policy == "random":
            self.rng.shuffle(self.order)
        self.remote = {}
        self.inflight = Counter()
        self.failures = Counter()
        self.banned = {}

    def clear(self):
        with self.lock:
            self.remote.clear()

    def update(self, file, peer, endpoint, bits):
        with self.lock:
            key = file, peer
            if bits is None:
                self.remote.pop(key, None)
            else:
                self.remote[key] = endpoint, bits

    def prune(self, allowed):
        """명단에서 빠진 소스와 완성된 파일의 캐시를 비움."""
        with self.lock:
            for key in self.remote.keys() - allowed:
                del self.remote[key]

    def choose(self, store):
        """정책으로 청크를 고르고 예약과 상대 요청 수를 함께 반영함."""
        files = {f.name: f for f in store.snapshot().files}
        with self.lock:
            now = monotonic()
            sources = {}
            for (name, pid), (endpoint, bits) in self.remote.items():
                if self.banned.get(pid, 0) <= now:
                    sources.setdefault(name, []).append((pid, endpoint, bits))
            candidates = []
            for name, idx in self.order:
                f = files[name]
                if f.state != FileState.DOWN or not f.prepared or f.bitmap[idx] == "1" or idx in f.in_progress:
                    continue
                holders = [(pid, address) for pid, address, bits in sources.get(name, ()) if bits[idx] == "1"]
                ready = [(pid, address) for pid, address in holders if self.inflight[pid] < self.limit]
                if ready:
                    candidates.append((len(holders), name, idx, ready))
                    if self.policy == "random":
                        break
            if self.policy == "rarest":
                self.rng.shuffle(candidates)
                candidates.sort(key=lambda candidate: candidate[0])
            for _, name, idx, ready in candidates:
                token = store.reserve(name, idx)
                if token is None:
                    continue
                least = min(self.inflight[pid] for pid, _ in ready)
                pid, address = self.rng.choice([item for item in ready if self.inflight[item[0]] == least])
                self.inflight[pid] += 1
                f = files[name]
                return token, pid, address, min(f.chunk_size, f.size-idx*f.chunk_size)
        return None

    def has_source(self, file):
        """미보유 청크 중 하나라도 현재 받을 곳이 있는지 확인함."""
        with self.lock:
            now = monotonic()
            return any(name == file.name and self.banned.get(pid, 0) <= now
                       and any(a == "0" and b == "1" for a, b in zip(file.bitmap, bits))
                       for (name, pid), (_, bits) in self.remote.items())

    def finish(self, file, pid, result):
        """요청 자리를 반환하고 연속 실패만 BAN으로 집계함."""
        with self.lock:
            self.inflight[pid] -= 1
            if result == "ok":
                self.failures[pid] = 0
            elif result == "fail":
                self.remote.pop((file, pid), None)
                self.failures[pid] += 1
                if self.failures[pid] >= self.fail_limit:
                    self.failures[pid] = 0
                    self.banned[pid] = monotonic() + self.ban_sec
                    return True
            return False
