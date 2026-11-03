from pathlib import Path
import json
import tempfile
import unittest

from tools.verify_run import verify_run_directory
from fixture import change_log, make_run


class VerifyRunTests(unittest.TestCase):
    def test_valid_fixture(self):
        with tempfile.TemporaryDirectory() as name:
            run = make_run(Path(name) / "run", n=4, n_mode="random")
            _, errors, _ = verify_run_directory(run)
            self.assertEqual(errors, [])

    def test_missing_and_extra_frame_fail(self):
        with tempfile.TemporaryDirectory() as name:
            run = make_run(Path(name) / "run")
            (run / "frames" / "frame0100.txt").unlink()
            (run / "frames" / "frame9999.txt").write_bytes(b"x")
            _, errors, _ = verify_run_directory(run)
            self.assertTrue(any("frame 파일 구성" in error for error in errors))

    def test_hash_and_crlf_fail(self):
        with tempfile.TemporaryDirectory() as name:
            run = make_run(Path(name) / "run")
            path = run / "round0100.txt"
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
            _, errors, _ = verify_run_directory(run)
            self.assertTrue(any("CRLF" in error or "12880" in error for error in errors))

    def test_round_hash_and_log_crlf_fail(self):
        with tempfile.TemporaryDirectory() as name:
            run = make_run(Path(name) / "run")
            hash_path = run / "RoundHash.txt"
            hash_path.write_bytes(hash_path.read_bytes().replace(b"\n", b"\r\n"))
            log_path = run / "logs" / "Assigner.txt"
            log_path.write_bytes(log_path.read_bytes().replace(b"\n", b"\r\n"))
            _, errors, _ = verify_run_directory(run)
            self.assertTrue(any("RoundHash" in error and "LF" in error for error in errors))
            self.assertTrue(any("Assigner.txt" in error and "LF" in error for error in errors))

    def test_log_run_id_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as name:
            run = make_run(Path(name) / "run")
            path = run / "logs" / "Worker0.txt"
            text = path.read_text(encoding="utf-8").replace('"run_id":"test-n1"',
                                                              '"run_id":"other"', 1)
            path.write_text(text, encoding="utf-8", newline="\n")
            _, errors, _ = verify_run_directory(run)
            self.assertTrue(any("run_id가 다릅니다" in error for error in errors))

    def test_mixed_input_hash_fails(self):
        with tempfile.TemporaryDirectory() as name:
            run = make_run(Path(name) / "run")
            info = run / "run_info.json"
            text = info.read_text(encoding="utf-8")
            text = text.replace('"canvas0.txt": "', '"canvas0.txt": "0', 1)
            info.write_text(text, encoding="utf-8", newline="\n")
            _, errors, _ = verify_run_directory(run)
            self.assertTrue(any("SHA-256" in error or "canvas0" in error for error in errors))

    def test_statistics_and_worker_contract_fail(self):
        with tempfile.TemporaryDirectory() as name:
            run = make_run(Path(name) / "run", n=4, n_mode="random")
            assigner = run / "logs" / "Assigner.txt"
            change_log(assigner, "BARRIER", {
                "normal_bytes": -1,
                "full_bytes": 2000.5,
                "slowest_counts": {"0": 100, "1": 0, "2": 0, "3": -1},
            })
            change_log(assigner, "TERMINATE", {
                "normal_rounds": 2699,
                "full_rounds": 301,
                "slowest_workers": [3],
            })

            worker = run / "logs" / "Worker0.txt"
            change_log(worker, "INIT", {
                "connect_timeout_s": -1.0,
                "startup_timeout_s": 999.0,
                "io_timeout_s": -2.0,
            })
            change_log(worker, "REPAINT", {
                "canvas": "canvas2.txt",
                "conversion": "cyclic",
            })
            _, errors, _ = verify_run_directory(run)
            self.assertTrue(any("normal_bytes" in error for error in errors))
            self.assertTrue(any("slowest_counts" in error for error in errors))
            self.assertTrue(any("2700" in error or "normal_rounds" in error
                                for error in errors))
            self.assertTrue(any("제한시간" in error for error in errors))
            self.assertTrue(any("Worker0 INIT" in error and "다릅니다" in error
                                for error in errors))
            self.assertTrue(any("Worker0.txt: REPAINT" in error for error in errors))

    def test_aggregate_statistics_must_match_barriers(self):
        with tempfile.TemporaryDirectory() as name:
            run = make_run(Path(name) / "run", n=4, n_mode="random")
            assigner = run / "logs" / "Assigner.txt"
            change_log(assigner, "TERMINATE", {
                "normal_bytes": 30001,
                "normal_avg_bytes": 30001/2700,
                "slowest_counts": {"0": 751, "1": 749, "2": 750, "3": 750},
                "slowest_workers": [0],
            })
            _, errors, _ = verify_run_directory(run)
            self.assertTrue(any("normal_bytes가 BARRIER 합계" in error for error in errors))
            self.assertTrue(any("slowest_counts가 BARRIER 합계" in error for error in errors))

    def test_duplicate_save_wrong_state_and_extra_snapshot_fail(self):
        with tempfile.TemporaryDirectory() as name:
            run = make_run(Path(name) / "run")
            assigner = run / "logs" / "Assigner.txt"
            change_log(assigner, "SAVE", {"state_round": 123})
            lines = assigner.read_text(encoding="utf-8").splitlines()
            duplicate = next(line for line in lines if " | SAVE | SUCCESS | " in line)
            assigner.write_text("\n".join(lines + [duplicate]) + "\n",
                                encoding="utf-8", newline="\n")
            (run / "frames" / "frame_bad.txt").write_text("extra", encoding="ascii")
            (run / "snapshot_bad.txt").write_text("extra", encoding="ascii")
            _, errors, _ = verify_run_directory(run)
            self.assertTrue(any("SAVE 기록이 누락되거나 중복" in error for error in errors))
            self.assertTrue(any("상태 번호" in error for error in errors))
            self.assertTrue(any("round 파일 구성" in error for error in errors))
            self.assertTrue(any("frame 파일 구성" in error for error in errors))

    def test_invalid_timeouts_metadata_returns_failure(self):
        with tempfile.TemporaryDirectory() as name:
            run = make_run(Path(name) / "run")
            path = run / "run_info.json"
            info = json.loads(path.read_text(encoding="utf-8"))
            info["timeouts"] = None
            path.write_text(json.dumps(info, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
            checked, errors, _ = verify_run_directory(run)
            self.assertIsNone(checked["timeouts"])
            self.assertTrue(any("timeouts 형식" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

