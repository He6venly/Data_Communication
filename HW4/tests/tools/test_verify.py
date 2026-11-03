from pathlib import Path
import tempfile
import unittest

from tools.verify_run import verify_run_directory
from fixture import make_run


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


if __name__ == "__main__":
    unittest.main()

