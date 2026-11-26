"""Tracker 2단위 검사용 대역 시계·피어·작은 env를 제공함."""

from copy import deepcopy
from hashlib import sha256
import unittest

from src.tracker.state import TrackerState


def make_env():
    """파일 크기·청크·포트가 공개 Run과 다른 검사 설정을 만듦."""
    files = [dict(name=n, size=len(data), origin=p, sha256=sha256(data).hexdigest())
             for n, data, p in [("a.bin", b"abcdefghijk", "P1"),
                                ("b.bin", b"12345678", "P2"), ("c.bin", b"x", "P3")]]
    return dict(version=1, name="UNIT2", run="A", seed=-7, description="Tracker 상태 검사",
                tracker=dict(port=16000), chunk_size=8, files=files,
                peers=[dict(id=f"P{i}", host=f"127.0.0.{i}", port=17000+i,
                            dir=f"p{i}", up_kbps=100+i, down_kbps=90+i) for i in range(1, 5)],
                progress_total_chunks=12,
                download=dict(workers=8, per_peer_max=4, policy="random", policy_seed=-3),
                timing=dict(heartbeat_sec=2, bitmap_refresh_sec=1, peers_refresh_sec=3,
                            dead_sec=20, stall_sec=30, hang_sec=60, deadline_sec=900,
                            status_every_sec=5, fail_limit=3, ban_sec=5,
                            report_stale_sec=3, tracker_lost_sec=30),
                crashes=[], destroy=None)


class Clock:
    """시작 시각과 경과 시간을 잠들지 않고 변경함."""

    def __init__(self):
        """0초 START와 절대 시각을 혼동하지 않도록 100초에서 시작함."""
        self.now = 100.0

    def __call__(self):
        """현재 대역 단조 시각을 반환함."""
        return self.now

    def advance(self, seconds):
        """검사할 경계 시각까지 시계를 앞으로 이동함."""
        assert seconds >= 0
        self.now += seconds


class StateCase(unittest.TestCase):
    """정상 참가·등록·REPORT를 대역 Peer 명령으로 조립함."""

    def setUp(self):
        """매 검사마다 독립 상태·시계·이벤트 수집기를 준비함."""
        self.env = make_env()
        self.clock = Clock()
        self.events = []
        self.state = self.make_state(self.env)

    def make_state(self, env):
        """이벤트가 상태 Lock 밖에서 호출되는지도 함께 검사함."""
        def emit(event, **fields):
            self.assertTrue(state.lock.acquire(blocking=False), "event I/O held state lock")
            state.lock.release()
            state.snapshot()
            self.events.append((event, deepcopy(fields)))
        state = TrackerState(env=env, emit=emit, clock=self.clock)
        return state

    def cmd(self, line, pid=None):
        """대역 명령을 보내고 응답 줄 복사본을 얻음."""
        return self.state.handle(line, peer_id=pid, src_ip="203.0.113.77")

    def join_all(self):
        """env 피어 네 명을 HELLO시켜 START를 고정함."""
        for i in range(1, 5):
            self.assertEqual(self.cmd(f"HELLO P{i}").lines, ("OK",))

    def register_all(self):
        """각 원본 피어가 자기 파일을 REGISTER함."""
        for f in self.env["files"]:
            p = next(p for p in self.env["peers"] if p["id"] == f["origin"])
            self.assertEqual(self.cmd(f"REGISTER {p['id']} {p['port']} {f['name']} {f['size']} 8").lines, ("OK",))

    def report(self, pid, name, bits, sent=0, distinct=0):
        """길이가 짧은 실제 REPORT 메시지를 만들어 전송함."""
        self.assertEqual(self.cmd(f"REPORT {pid} {name} {sent} {distinct} {bits}").lines, ("OK",))

    def keep_alive(self, *ids):
        """선택한 피어의 liveness만 갱신하고 have는 유지함."""
        have = self.state.snapshot()["have"]
        for pid in ids:
            self.cmd(f"HEARTBEAT {pid} {have[pid]}")

    def event_fields(self, name):
        """지정한 이벤트의 필드 복사본만 추려 반환함."""
        return [fields for event, fields in self.events if event == name]
