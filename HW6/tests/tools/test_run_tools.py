"""실행 기동과 결과 기록 검사 도구를 검증한다."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.check_run import _lost, validate
from tools.collect_run import main as collect_main
from tools.launch_peers import main as launch_main


def sample_env() -> dict:
    """검사 도구에 필요한 최소 4-Peer env를 만든다."""
    return {
        "name": "A", "run": "A", "chunk_size": 2,
        "download": {"policy": "random"},
        "files": [{"name": "one.bin", "size": 4, "origin": "P1", "sha256": "a" * 64}],
        "peers": [
            {"id": f"P{i}", "dir": f"p{i}", "up_kbps": 100, "down_kbps": 100}
            for i in range(1, 5)
        ],
        "destroy": None,
    }


class RunToolTests(unittest.TestCase):
    """CLI 오류와 기록 누락을 성공 사례와 비교한다."""

    def test_lost_ranges(self) -> None:
        """빠진 청크를 오름차순 연속 구간 문자열로 묶는다."""
        self.assertEqual(_lost("10110001"), "1,4-6")
        self.assertEqual(_lost("111"), "")

    def test_validate_complete_record_and_detect_bad_lost(self) -> None:
        """5개 로그와 report·bitmap 기록을 검사하고 lost 불일치를 잡는다."""
        env = sample_env()
        with tempfile.TemporaryDirectory(prefix="hw6-run-check-") as tmp:
            run_dir = Path(tmp)
            (run_dir / "logs").mkdir()
            for peer in env["peers"]:
                peer_id = peer["id"]
                rows = [
                    {"t": 0.0, "peer": peer_id, "ev": "START", "policy": "random"},
                    {"t": 10.0, "peer": peer_id, "ev": "EXIT", "code": 0, "up_mb": 0.0, "down_mb": 0.0},
                ]
                (run_dir / "logs" / f"{peer_id}.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
                )
                peer_dir = run_dir / peer["dir"]
                peer_dir.mkdir()
                (peer_dir / "one.bin.bitmap").write_text("11", encoding="ascii")
            tracker_rows = [
                {"t": 0.0, "peer": "tracker", "ev": "START_PROGRAM"},
                {"t": 10.0, "peer": "tracker", "ev": "EXIT"},
            ]
            (run_dir / "logs" / "tracker.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in tracker_rows), encoding="utf-8"
            )
            report = {
                "env": "A", "run": "A", "seed": 1, "policy": "random", "destroy_plan": None,
                "crashes_sent": 0, "T_rep": {}, "p_rep": None, "upstat_at_rep": {},
                "dup_ratio": {}, "T_destroy": None, "p_destroy": None, "T_dead": {},
                "T_done": {}, "T_last_done": None, "T_alldone": 10.0, "T_exit": 10.0,
                "done_kind": {}, "peers": {}, "abort": None,
            }
            (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
            (run_dir / "verify.txt").write_text("RESULT: PASS\n", encoding="utf-8")
            self.assertEqual(validate(env, run_dir), [])

            (run_dir / "p3" / "one.bin.bitmap").write_text("10", encoding="ascii")
            (run_dir / "p3" / "one.bin.lost").write_text("1", encoding="ascii")
            self.assertTrue(any("bitmap" in issue or "수렴" in issue for issue in validate(env, run_dir)))

    def test_launcher_requires_c3_policy_before_spawning(self) -> None:
        """C3 정책이 없으면 자식 프로세스를 만들기 전에 종료한다."""
        env = sample_env()
        env["name"] = "C3"
        env["download"]["policy"] = None
        with tempfile.TemporaryDirectory(prefix="hw6-launch-") as tmp:
            path = Path(tmp) / "C3.json"
            path.write_text(json.dumps(env), encoding="utf-8")
            with patch("tools.launch_peers.subprocess.Popen") as popen:
                code = launch_main(["--env", str(path), "127.0.0.1", "6000"])
            self.assertEqual(code, 1)
            popen.assert_not_called()

    def test_launcher_starts_four_peers_with_selected_policy(self) -> None:
        """명시한 정책과 tracker 주소를 네 Peer 명령에 전달한다."""
        env = sample_env()

        class FakeProcess:
            def wait(self) -> int:
                return 0

        with tempfile.TemporaryDirectory(prefix="hw6-launch-") as tmp:
            path = Path(tmp) / "A.json"
            path.write_text(json.dumps(env), encoding="utf-8")
            with patch("tools.launch_peers.subprocess.Popen", side_effect=lambda *_args, **_kwargs: FakeProcess()) as popen:
                code = launch_main(["--env", str(path), "--policy", "rarest", "192.0.2.1", "6100"])
            self.assertEqual(code, 0)
            self.assertEqual(popen.call_count, 4)
            for call in popen.call_args_list:
                self.assertIn("rarest", call.args[0])
                self.assertEqual(call.args[0][-2:], ["192.0.2.1", "6100"])

    def test_collect_run_saves_only_checked_record_files(self) -> None:
        """공식 검사 뒤 로그·report·verify·bitmap/lost만 새 Run에 보관한다."""
        env = sample_env()
        with tempfile.TemporaryDirectory(prefix="hw6-collect-") as tmp:
            root = Path(tmp)
            kit = root / "kit"
            (kit / "tools").mkdir(parents=True)
            (kit / "tools" / "verify.py").write_text("# fixture", encoding="utf-8")
            env_path = root / "A.json"
            env_path.write_text(json.dumps(env), encoding="utf-8")
            (root / "logs").mkdir()
            for peer in env["peers"]:
                peer_id = peer["id"]
                rows = [
                    {"t": 0.0, "peer": peer_id, "ev": "START", "policy": "random"},
                    {"t": 10.0, "peer": peer_id, "ev": "EXIT", "code": 0, "up_mb": 0.0, "down_mb": 0.0},
                ]
                (root / "logs" / f"{peer_id}.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
                )
                peer_dir = root / peer["dir"]
                peer_dir.mkdir()
                (peer_dir / "one.bin.bitmap").write_text("11", encoding="ascii")
                # 데이터 파일은 결과 폴더로 복사하지 않는지 확인하는 더미 입력이다.
                (peer_dir / "one.bin").write_bytes(b"not copied")
            tracker_rows = [
                {"t": 0.0, "peer": "tracker", "ev": "START_PROGRAM"},
                {"t": 10.0, "peer": "tracker", "ev": "EXIT"},
            ]
            (root / "logs" / "tracker.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in tracker_rows), encoding="utf-8"
            )
            report = {
                "env": "A", "run": "A", "seed": 1, "policy": "random", "destroy_plan": None,
                "crashes_sent": 0, "T_rep": {}, "p_rep": None, "upstat_at_rep": {},
                "dup_ratio": {}, "T_destroy": None, "p_destroy": None, "T_dead": {},
                "T_done": {}, "T_last_done": None, "T_alldone": 10.0, "T_exit": 10.0,
                "done_kind": {}, "peers": {}, "abort": None,
            }
            (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
            runs = root / "runs"
            args = ["--env", str(env_path), "--kit", str(kit), "--run-name", "A", "--runs-dir", str(runs)]
            result = SimpleNamespace(returncode=0, stdout="RESULT: PASS\n")
            with patch("tools.collect_run.Path.cwd", return_value=root), patch("tools.collect_run.subprocess.run", return_value=result):
                self.assertEqual(collect_main(args), 0)
            saved = runs / "A"
            self.assertTrue((saved / "verify.txt").is_file())
            self.assertTrue((saved / "p1" / "one.bin.bitmap").is_file())
            self.assertFalse((saved / "p1" / "one.bin").exists())


if __name__ == "__main__":
    unittest.main()
