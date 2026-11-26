"""최종 report 스키마·종료 고정·원자적 파일 저장을 검사함."""

import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from src.common.contracts import LifecycleError
from src.tracker.report import write_report
from unit2_support import StateCase


KEYS = ("env run seed policy destroy_plan crashes_sent T_rep p_rep upstat_at_rep dup_ratio "
        "T_destroy p_destroy T_dead T_done T_last_done T_alldone T_exit done_kind peers abort").split()


class ReportTests(StateCase):
    """대역 정상 종료와 실제 임시 파일로 보고서 생성을 확인함."""

    def finish(self):
        """네 피어를 정상 완료·퇴장시켜 최종 report를 반환함."""
        for i in range(1, 5):
            self.cmd(f"DONE P{i} FULL")
        for i in range(1, 5):
            self.cmd(f"BYE P{i}")
        self.assertEqual(self.state.exit_code(), 0)
        return self.state.prepare_report()

    def test_exact_schema_nulls_and_frozen_snapshot(self):
        """정식 키 순서·null·START 기준 시각과 반환값 격리를 확인함."""
        self.join_all()
        with self.assertRaises(LifecycleError):
            self.state.prepare_report()
        self.clock.advance(1.234)
        report = self.finish()
        self.assertEqual(list(report), KEYS)
        self.assertEqual(report["T_exit"], 1.23)
        self.assertEqual(report["T_alldone"], 1.23)
        self.assertEqual(report["T_last_done"], 1.23)
        self.assertEqual(report["T_done"], dict.fromkeys([f"P{i}" for i in range(1, 5)], 1.23))
        self.assertEqual(report["T_rep"], dict.fromkeys(["a.bin", "b.bin", "c.bin"]))
        self.assertEqual(report["peers"], dict.fromkeys([f"P{i}" for i in range(1, 5)], "BYE"))
        self.assertIsNone(report["p_rep"])
        self.assertIsNone(report["abort"])
        report["destroy_plan"] = {}
        report["T_done"].clear()
        self.clock.advance(100)
        self.state.tick()
        self.state.observe()
        self.assertEqual(self.state.prepare_report()["T_exit"], 1.23)
        self.assertEqual(len(self.state.prepare_report()["T_done"]), 4)

    def test_duplication_stats_and_zero_sent(self):
        """복제 당시 통계로 중복률을 계산하고 0 송출·미보고를 구분함."""
        self.join_all()
        self.report("P1", "a.bin", "11", 5, 2)
        self.report("P2", "a.bin", "11")
        self.report("P2", "b.bin", "1", 0, 0)
        self.report("P1", "b.bin", "1")
        self.report("P1", "c.bin", "1")
        self.state.observe()
        result = self.finish()
        self.assertEqual(result["upstat_at_rep"], {"a.bin": [5, 2], "b.bin": [0, 0], "c.bin": None})
        self.assertEqual(result["dup_ratio"], {"a.bin": .6, "b.bin": None, "c.bin": None})
        self.assertEqual(result["p_rep"], 0)

    def test_final_report_waits_for_delivery_callback(self):
        """송신 중 지시가 있으면 실제 성공·실패 확정 전 report를 고정하지 않음."""
        self.env["crashes"] = [dict(peer="P1", at_sec=0, duration_sec=2)]
        self.state = self.make_state(self.env)
        self.join_all()
        self.state.tick()
        reply = self.cmd("HEARTBEAT P1 0")
        for i in range(1, 5):
            self.cmd(f"DONE P{i} FULL")
            self.cmd(f"BYE P{i}")
        self.assertFalse(self.state.delivery_valid(reply.delivery_token))
        with self.assertRaises(LifecycleError):
            self.state.prepare_report()
        self.assertTrue(self.state.delivery_succeeded(reply.delivery_token))
        self.assertEqual(len(self.state.prepare_report()["crashes_sent"]), 1)

    def test_explicit_dead_required_and_abort_early_exit(self):
        """시간 경과만으로 DEAD 로그를 생략하지 않고 ABORT는 조기 퇴장 가능함."""
        self.join_all()
        for i in range(1, 5):
            self.cmd(f"DONE P{i} FULL")
        self.clock.advance(21)
        self.assertIsNone(self.state.exit_code())
        self.state.tick()
        self.assertEqual(self.state.exit_code(), 0)
        self.assertEqual(len(self.event_fields("DEAD")), 4)
        self.assertEqual(set(self.state.prepare_report()["peers"].values()), {"DEAD"})
        self.env["timing"]["deadline_sec"] = 1
        self.state = self.make_state(self.env)
        self.join_all()
        self.clock.advance(2)
        self.state.tick()
        for i in range(1, 5):
            self.cmd(f"BYE P{i}")
        self.assertEqual(self.state.exit_code(), 2)
        self.assertEqual(self.state.prepare_report()["abort"], "deadline")

    def test_atomic_utf8_write_and_invalid_payload_preserves_previous(self):
        """UTF-8·LF·들여쓰기를 지키고 직렬화 실패 시 기존 결과를 보존함."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "한글" / "report.json"
            write_report(path, {"설명": "검사", "T_exit": 1.23})
            original = path.read_bytes()
            self.assertNotIn(b"\r", original)
            self.assertIn('  "설명"'.encode(), original)
            self.assertEqual(json.loads(original), {"설명": "검사", "T_exit": 1.23})
            with self.assertRaises(ValueError):
                write_report(path, {"invalid": float("nan")})
            self.assertEqual(path.read_bytes(), original)
            with patch("src.tracker.report.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    write_report(path, {"new": True})
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(".report-*.tmp")), [])

