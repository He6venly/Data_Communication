"""명령·참가·등록·완료를 네트워크와 분리해 검사함."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from unit2_support import StateCase


class StateTests(StateCase):
    def test_start_once_and_env_is_not_modified(self):
        """마지막 HELLO에서만 START가 생성되고 원본 env가 보존되는지 확인함."""
        original = deepcopy(self.env)
        self.cmd("HELLO P1")
        self.cmd("HELLO P1")
        self.cmd("HELLO P2")
        self.cmd("HELLO P3")
        self.assertIsNone(self.state.snapshot()["started_at"])
        self.clock.advance(10)
        self.cmd("HELLO P4")
        self.cmd("HELLO P4")
        self.assertEqual(self.state.snapshot()["started_at"], 110)
        self.assertEqual(len(self.event_fields("START")), 1)
        self.assertEqual(len(self.event_fields("JOIN")), 4)
        self.assertEqual(self.env, original)
        self.env["timing"]["dead_sec"] = 1
        self.assertEqual(self.state.env["timing"]["dead_sec"], 20)

    def test_registration_race_and_multiline_catalog(self):
        """LIST 대기와 HAVE 재시도에 필요한 초기 응답을 확인함."""
        self.join_all()
        self.assertEqual(self.cmd("LIST").lines, ("FILES 0",))
        self.assertEqual(self.cmd("HAVE P4 17004 a.bin").lines, ("ERR NOFILE",))
        self.assertEqual(self.cmd("REGISTER P1 17001 a.bin 11 8").lines, ("OK",))
        self.assertEqual(self.cmd("LIST").lines, ("FILES 1", "a.bin 11 8 2 1"))
        self.assertEqual(self.cmd("HAVE P4 17004 a.bin").lines, ("OK",))
        self.assertEqual(self.cmd("PEERS a.bin").lines,
                         ("PEERS 2", "P1 127.0.0.1 17001", "P4 127.0.0.4 17004"))
        self.cmd("HAVE P4 17004 a.bin")
        self.assertEqual(self.cmd("LIST").lines[-1], "a.bin 11 8 2 2")

    def test_registration_mismatch_and_unknown_file(self):
        """등록 크기·포트 불일치가 명단을 오염시키지 않는지 확인함."""
        self.join_all()
        for line in ("REGISTER P1 17001 a.bin 12 8", "REGISTER P1 17002 a.bin 11 8",
                     "REGISTER P1 17001 a.bin 11 9", "REGISTER P1 17001 missing 1 8"):
            with self.subTest(line=line):
                self.assertEqual(self.cmd(line).lines, ("ERR MISMATCH",))
        self.assertEqual(self.cmd("LIST").lines, ("FILES 0",))
        self.assertEqual(self.cmd("PEERS missing").lines, ("ERR NOFILE",))

    def test_bad_commands_remain_usable(self):
        """잘못된 메시지 뒤에도 같은 연결 문맥으로 정상 명령을 처리함."""
        self.join_all()
        for line in ("", "UNKNOWN", "LIST extra", "HELLO P9", "REGISTER P1", "HEARTBEAT P1 -1",
                     "HEARTBEAT P1 3", "HEARTBEAT P1 nan", "REPORT P1 a.bin 2 3 11",
                     "REPORT P1 a.bin 0 0 1", "REPORT P1 a.bin 0 0 1x", "DONE P1 PARTIAL",
                     "DONE P1 FULL extra", "DONE P1 PARTIAL a.bin:0", "DONE P1 PARTIAL a.bin:3",
                     "DONE P1 PARTIAL a.bin:1 a.bin:1", "DONE P1 PARTIAL absent:1",
                     "UNDONE", "BYE P9", "STATE\nHELLO P1"):
            with self.subTest(line=line):
                self.assertEqual(self.cmd(line, "P1").lines, ("ERR BADCMD",))
                self.assertEqual(self.cmd("LIST", "P1").lines, ("FILES 0",))
        self.assertEqual(self.state.snapshot()["have"]["P1"], 0)

    def test_identity_commands_without_persistent_socket(self):
        """HELLO 후 연결을 다시 열어도 명령 id로 liveness를 갱신함."""
        self.join_all()
        self.clock.advance(19)
        self.cmd("HEARTBEAT P1 1")
        self.assertEqual(self.state.snapshot()["last_seen"]["P1"], 119)
        self.assertEqual(self.cmd("STATE").lines, ("STATE 0 4 WAIT",))

    def test_done_undone_and_idempotent_time(self):
        """PARTIAL·FAILED·중복 DONE·UNDONE의 상태 전이를 확인함."""
        self.join_all()
        self.clock.advance(1)
        self.assertEqual(self.cmd("DONE P1 PARTIAL c.bin:FAILED b.bin:1").lines, ("OK",))
        self.clock.advance(1)
        self.cmd("DONE P1 PARTIAL b.bin:1 c.bin:FAILED")
        self.assertEqual(self.state.snapshot()["T_done"]["P1"], 1)
        self.assertEqual(len(self.event_fields("DONE")), 1)
        self.cmd("UNDONE P1")
        self.cmd("UNDONE P1")
        self.assertNotIn("P1", self.state.snapshot()["done"])
        self.assertNotIn("P1", self.state.snapshot()["T_done"])
        self.assertEqual(len(self.event_fields("UNDONE")), 1)
        self.cmd("DONE P1 FULL")
        self.assertEqual(self.state.snapshot()["T_done"]["P1"], 2)

    def test_snapshots_do_not_expose_mutable_state(self):
        """반환된 복사본을 바꿔도 내부 진행률·완료 상태가 보존되는지 확인함."""
        self.join_all()
        snap = self.state.snapshot()
        snap["have"]["P1"] = 999
        snap["done"]["P1"] = ("FULL", "")
        self.assertEqual(self.state.snapshot()["have"]["P1"], 0)
        self.assertEqual(self.state.snapshot()["done"], {})

    def test_concurrent_requests_and_callbacks(self):
        """동시 요청과 상태를 재조회하는 로그 콜백에서 교착이 없는지 확인함."""
        self.join_all()
        self.register_all()

        def work(index):
            """각 대역 피어가 같은 시각에 REPORT·조회·heartbeat를 반복함."""
            pid = f"P{index % 4 + 1}"
            for _ in range(30):
                self.report(pid, "a.bin", "10")
                self.cmd("PEERS a.bin", pid)
                self.cmd(f"HEARTBEAT {pid} 0")
            return True

        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertTrue(all(pool.map(work, range(16))))
        self.assertEqual(self.state.snapshot()["have"], {"P1": 0, "P2": 0, "P3": 0, "P4": 0})
