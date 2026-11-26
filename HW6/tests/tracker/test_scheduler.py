"""장애·생존·종료의 정확한 경계와 송신 재시도를 검사함."""

from src.common.contracts import LifecycleError
from unit2_support import StateCase


class SchedulerTests(StateCase):
    def test_dead_boundary_back_and_holder_filter(self):
        """20초까지는 live이고 초과하면 DEAD·재수신하면 BACK인지 확인함."""
        self.join_all()
        self.register_all()
        self.clock.advance(20)
        self.state.tick()
        self.assertEqual(self.state.snapshot()["dead"], ())
        self.keep_alive("P2", "P3", "P4")
        self.clock.advance(0.001)
        self.state.tick()
        self.assertEqual(self.state.snapshot()["dead"], ("P1",))
        self.assertEqual(self.cmd("PEERS a.bin").lines, ("PEERS 0",))
        self.state.tick()
        self.assertEqual(len(self.event_fields("DEAD")), 1)
        self.cmd("LIST", "P1")
        self.assertEqual(self.state.snapshot()["dead"], ())
        self.assertEqual(len(self.event_fields("BACK")), 1)
        self.assertEqual(self.cmd("PEERS a.bin").lines[-1], "P1 127.0.0.1 17001")
        self.cmd("BYE P1")
        self.assertEqual(self.cmd("PEERS a.bin").lines, ("PEERS 0",))

    def test_no_start_no_schedule_or_watchdog(self):
        """네 명 참가 전에는 장애·deadline·hang 시계를 진행하지 않음."""
        self.env["crashes"] = [dict(peer="P1", at_sec=0, duration_sec=1)]
        self.state = self.make_state(self.env)
        self.cmd("HELLO P1")
        self.clock.advance(1000)
        self.state.tick()
        self.state.observe()
        self.assertEqual(self.state.snapshot()["pending"]["P1"], ())
        self.assertIsNone(self.state.snapshot()["abort"])
        self.assertIsNone(self.state.exit_code())

    def test_crash_due_exact_time_and_delivery_retry(self):
        """지시 등록과 실제 송신을 나누고 실패한 지시를 다시 전달함."""
        self.env["crashes"] = [dict(peer="P2", at_sec=5, duration_sec=2.123456789)]
        self.state = self.make_state(self.env)
        self.join_all()
        self.clock.advance(4.999)
        self.state.tick()
        self.assertEqual(self.state.snapshot()["pending"]["P2"], ())
        self.clock.advance(0.001)
        self.state.tick()
        self.assertEqual(len(self.event_fields("CMD")), 1)
        self.assertEqual(self.state.snapshot()["crashes_sent"], [])
        reply = self.cmd("HEARTBEAT P2 0")
        self.assertEqual(reply.lines, ("CMD DISCONNECT 2.123456789",))
        self.assertTrue(self.state.delivery_valid(reply.delivery_token))
        self.assertEqual(self.cmd("HEARTBEAT P2 0").lines, ("OK",))
        self.state.delivery_failed(reply.delivery_token)
        retry = self.cmd("HEARTBEAT P2 0")
        self.assertEqual(retry.lines, reply.lines)
        self.assertTrue(self.state.delivery_succeeded(retry.delivery_token))
        self.assertFalse(self.state.delivery_succeeded(retry.delivery_token))
        self.assertEqual(self.state.snapshot()["crashes_sent"],
                         [dict(t=5.0, peer="P2", cmd="DISCONNECT", sec=2.123456789)])
        self.state.tick()
        self.assertEqual(len(self.event_fields("CMD_DELIVERED")), 1)

    def test_same_peer_crashes_are_not_overwritten(self):
        """같은 피어의 겹친 일정도 대기열에서 하나씩 전달함."""
        self.env["crashes"] = [dict(peer="P1", at_sec=1, duration_sec=2),
                               dict(peer="P1", at_sec=2, duration_sec=3)]
        self.state = self.make_state(self.env)
        self.join_all()
        self.clock.advance(2)
        self.state.tick()
        for duration in (2, 3):
            r = self.cmd("HEARTBEAT P1 0")
            self.assertEqual(r.lines, (f"CMD DISCONNECT {duration}",))
            self.state.delivery_succeeded(r.delivery_token)
        self.assertEqual(len(self.state.snapshot()["crashes_sent"]), 2)

    def test_time_and_progress_destroy(self):
        """두 파괴 기준을 반올림 전 시간·진행률로 판정함."""
        for trigger, value in (("time", 5), ("progress", 0.25)):
            with self.subTest(trigger=trigger):
                self.events.clear()
                self.env["destroy"] = dict(peer="P3", trigger=trigger, value=value, replica_safe=False)
                self.state = self.make_state(self.env)
                self.join_all()
                if trigger == "time":
                    self.clock.advance(4.999)
                else:
                    self.cmd("HEARTBEAT P4 2")
                self.state.tick()
                self.assertIsNone(self.state.snapshot()["T_destroy"])
                if trigger == "time":
                    self.clock.advance(0.001)
                else:
                    self.cmd("HEARTBEAT P4 3")
                self.state.tick()
                self.assertIsNotNone(self.state.snapshot()["T_destroy"])
                r = self.cmd("HEARTBEAT P3 0")
                self.assertEqual(r.lines, ("CMD DESTROY",))
                self.state.delivery_succeeded(r.delivery_token)
                self.state.tick()
                self.assertEqual(len(self.event_fields("CMD")), 1)

    def test_hang_deadline_and_progress_reset(self):
        """heartbeat만으로 hang을 연장하지 않고 실제 have 변화로 갱신함."""
        self.join_all()
        self.clock.advance(59.99)
        self.keep_alive("P1", "P2", "P3", "P4")
        self.state.tick()
        self.assertIsNone(self.state.snapshot()["abort"])
        self.cmd("HEARTBEAT P4 1")
        self.clock.advance(59.99)
        self.keep_alive("P1", "P2", "P3", "P4")
        self.state.tick()
        self.assertIsNone(self.state.snapshot()["abort"])
        self.clock.advance(0.01)
        self.state.tick()
        self.assertEqual(self.state.snapshot()["abort"], "stalled")
        self.env["timing"].update(deadline_sec=2, hang_sec=60)
        self.state = self.make_state(self.env)
        self.join_all()
        self.clock.advance(2)
        self.state.tick()
        self.assertIsNone(self.state.snapshot()["abort"])
        self.clock.advance(0.001)
        self.state.tick()
        self.assertEqual(self.state.snapshot()["abort"], "deadline")

    def test_done_partial_normal_exit_waits_for_dead_victim(self):
        """생존자 PARTIAL 완료도 정상이며 희생자 DEAD 판정까지 기다림."""
        self.join_all()
        for pid in ("P1", "P2", "P4"):
            self.cmd(f"DONE {pid} PARTIAL a.bin:1")
        self.clock.advance(20.001)
        self.keep_alive("P1", "P2", "P4")
        self.state.tick()
        self.assertTrue(self.cmd("STATE").lines[0].endswith("ALLDONE"))
        self.assertIsNone(self.state.exit_code())
        for pid in ("P1", "P2", "P4"):
            self.cmd(f"BYE {pid}")
        self.assertEqual(self.state.exit_code(), 0)
        report = self.state.prepare_report()
        self.assertEqual(report["peers"]["P3"], "DEAD")
        self.assertEqual(set(report["done_kind"].values()), {"PARTIAL"})
        with self.assertRaises(LifecycleError):
            self.cmd("HELLO P3")

    def test_empty_live_set_does_not_mean_alldone(self):
        """전원 침묵을 빈 집합의 전원 완료로 오판하지 않음."""
        self.join_all()
        self.clock.advance(20.001)
        self.state.tick()
        self.assertFalse(self.state.snapshot()["alldone"])
        self.assertIsNone(self.state.exit_code())

    def test_terminal_drops_pending_and_late_commands(self):
        """ALLDONE 뒤에는 기존 대기 지시와 늦게 도래한 지시를 전달하지 않음."""
        self.env["crashes"] = [dict(peer="P1", at_sec=0, duration_sec=1),
                               dict(peer="P2", at_sec=10, duration_sec=1)]
        self.state = self.make_state(self.env)
        self.join_all()
        self.state.tick()
        leased = self.cmd("HEARTBEAT P1 0")
        for pid in self.state.peers:
            self.cmd(f"DONE {pid} FULL")
        self.assertFalse(self.state.delivery_valid(leased.delivery_token))
        self.state.delivery_failed(leased.delivery_token)
        self.assertEqual(self.cmd("HEARTBEAT P1 0").lines, ("OK",))
        self.clock.advance(10)
        self.state.tick()
        self.assertEqual(len(self.event_fields("CMD_DROPPED")), 2)
        self.assertEqual(self.state.snapshot()["crashes_sent"], [])

    def test_abort_grace_and_early_departure(self):
        """ABORT 후 15초 만료 또는 전원 퇴장을 종료 조건으로 사용함."""
        self.env["timing"]["deadline_sec"] = 1
        self.state = self.make_state(self.env)
        self.join_all()
        self.clock.advance(1.001)
        self.state.tick()
        self.assertIsNone(self.state.exit_code())
        self.clock.advance(14.999)
        self.assertIsNone(self.state.exit_code())
        self.clock.advance(0.001)
        self.assertEqual(self.state.exit_code(), 2)
        self.assertEqual(self.state.prepare_report()["abort"], "deadline")
