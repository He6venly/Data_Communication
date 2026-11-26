"""fresh bitmap·복제 지표·안전 파괴의 경계 조건을 검사함."""

from unit2_support import StateCase


class ObserverTests(StateCase):
    """대역 REPORT를 조합해 파일별 사본과 파괴 기준을 확인함."""

    def test_origin_exclusion_union_and_first_observation(self):
        """원본을 제외한 여러 피어의 OR와 최초 관측 통계를 고정함."""
        self.join_all()
        self.report("P1", "a.bin", "11", 5, 2)
        self.state.observe()
        self.assertIsNone(self.state.snapshot()["T_rep"]["a.bin"])
        self.report("P2", "a.bin", "10")
        self.report("P3", "a.bin", "01")
        self.state.observe()
        self.assertEqual(self.state.snapshot()["T_rep"]["a.bin"], 0)
        self.assertEqual(self.state.snapshot()["upstat_at_rep"]["a.bin"], (5, 2))
        self.clock.advance(1)
        self.report("P1", "a.bin", "11", 8, 2)
        self.state.observe()
        self.assertEqual(self.state.snapshot()["upstat_at_rep"]["a.bin"], (5, 2))
        self.assertEqual(len(self.event_fields("REPLICATED")), 1)

    def test_report_staleness_exact_boundary(self):
        """3초 REPORT는 사용하고 3초 초과 REPORT는 제외함."""
        self.join_all()
        self.report("P2", "a.bin", "11")
        self.report("P1", "b.bin", "1")
        self.clock.advance(3)
        self.state.observe()
        self.assertEqual(self.state.snapshot()["T_rep"]["a.bin"], 3)
        self.clock.advance(.001)
        self.report("P1", "c.bin", "1")
        self.cmd("BYE P1")
        self.state.observe()
        self.assertIsNone(self.state.snapshot()["T_rep"]["c.bin"])
        self.report("P2", "c.bin", "1")
        self.clock.advance(3.001)
        self.state.observe()
        self.assertIsNone(self.state.snapshot()["T_rep"]["c.bin"])
        self.report("P4", "c.bin", "1")
        self.state.observe()
        self.assertIsNotNone(self.state.snapshot()["p_rep"])

    def test_dead_report_excluded_even_when_fresh(self):
        """DEAD 기준이 REPORT 유효기간보다 짧아도 live 조건을 적용함."""
        self.env["timing"]["dead_sec"] = 1
        self.state = self.make_state(self.env)
        self.join_all()
        self.report("P2", "a.bin", "11")
        self.clock.advance(1.5)
        self.state.observe()
        self.assertIsNone(self.state.snapshot()["T_rep"]["a.bin"])
        self.cmd("LIST", "P2")
        self.state.observe()
        self.assertEqual(self.state.snapshot()["T_rep"]["a.bin"], 1.5)

    def test_origin_last_stats_may_be_stale_or_missing(self):
        """복제 당시 마지막 원본 통계를 보존하고 미보고 값은 null로 둠."""
        self.join_all()
        self.report("P1", "a.bin", "11", 7, 2)
        self.clock.advance(4)
        self.report("P2", "a.bin", "11")
        self.report("P1", "b.bin", "1")
        self.state.observe()
        snap = self.state.snapshot()
        self.assertEqual(snap["upstat_at_rep"]["a.bin"], (7, 2))
        self.assertIsNone(snap["upstat_at_rep"]["b.bin"])
        self.assertIsNone(snap["p_rep"])

    def test_after_replication_uses_observed_progress_and_zero_time(self):
        """0초 복제도 인정하고 p_rep 이후 남은 진행량 비율로 파괴함."""
        self.env["destroy"] = dict(peer="P1", trigger="after_replication", value=.5, replica_safe=False)
        self.state = self.make_state(self.env)
        self.join_all()
        self.cmd("HEARTBEAT P4 2")
        self.report("P2", "a.bin", "11")
        self.report("P1", "b.bin", "1")
        self.report("P1", "c.bin", "1")
        self.state.tick()
        self.assertIsNone(self.state.snapshot()["T_destroy"])
        self.state.observe()
        self.assertEqual(self.state.snapshot()["p_rep"], 2/12)
        self.cmd("HEARTBEAT P1 2")
        self.cmd("HEARTBEAT P2 2")
        self.state.tick()
        self.assertIsNone(self.state.snapshot()["T_destroy"])
        self.cmd("HEARTBEAT P3 1")
        self.state.tick()
        self.assertEqual(self.state.snapshot()["T_destroy"], 0)
        self.assertEqual(self.state.snapshot()["p_destroy"], 7/12)

    def test_safe_destroy_checks_all_victim_files_and_freshness(self):
        """원본뿐 아니라 희생자가 받은 청크와 모든 최신 REPORT도 확인함."""
        self.env["destroy"] = dict(peer="P1", trigger="time", value=0, replica_safe=True)
        self.state = self.make_state(self.env)
        self.join_all()
        self.report("P1", "a.bin", "11")
        self.report("P2", "a.bin", "11")
        self.report("P1", "b.bin", "1")
        self.state.tick()
        self.assertIsNone(self.state.snapshot()["T_destroy"])
        self.report("P1", "c.bin", "0")
        self.state.tick()
        self.assertIsNone(self.state.snapshot()["T_destroy"])
        self.report("P3", "b.bin", "1")
        self.clock.advance(3.5)
        self.state.tick()
        self.assertIsNone(self.state.snapshot()["T_destroy"])
        for pid, name, bits in [("P1", "a.bin", "11"), ("P2", "a.bin", "11"),
                                ("P1", "b.bin", "1"), ("P3", "b.bin", "1"), ("P1", "c.bin", "0")]:
            self.report(pid, name, bits)
        self.state.tick()
        self.assertEqual(self.state.snapshot()["T_destroy"], 3.5)

    def test_destroy_precedes_unclaimed_crash_and_drops_it_after_delivery(self):
        """파괴 지시를 우선 전달하고 성공 뒤 같은 피어의 crash는 버림."""
        self.env["destroy"] = dict(peer="P1", trigger="time", value=0, replica_safe=False)
        self.env["crashes"] = [dict(peer="P1", at_sec=0, duration_sec=2)]
        self.state = self.make_state(self.env)
        self.join_all()
        self.state.tick()
        first = self.cmd("HEARTBEAT P1 0")
        self.assertEqual(first.lines, ("CMD DESTROY",))
        self.state.delivery_failed(first.delivery_token)
        second = self.cmd("HEARTBEAT P1 0")
        self.assertEqual(second.lines, first.lines)
        self.assertTrue(self.state.delivery_succeeded(second.delivery_token))
        self.assertEqual(self.cmd("HEARTBEAT P1 0").lines, ("OK",))
        self.assertEqual(self.state.snapshot()["crashes_sent"], [])

