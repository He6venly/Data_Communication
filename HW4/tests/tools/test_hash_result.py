from pathlib import Path
import tempfile
import unittest

from tools.make_hash_result import make_result
from fixture import change_log, make_run


class HashResultTests(unittest.TestCase):
    def test_three_valid_runs_pass(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            n1 = make_run(root / "n1", 1, "fixed")
            run4 = make_run(root / "run4", 4, "random")
            run6 = make_run(root / "run6", 6, "random")
            output = root / "hash_result.txt"
            errors, passed = make_result(2, n1, run4, run6, output)
            self.assertEqual(errors, [])
            self.assertTrue(passed)
            text = output.read_text(encoding="ascii")
            self.assertIn("TOTAL 31/31 SAME -> PASS", text)

    def test_different_result_writes_fail(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            n1 = make_run(root / "n1", 1, "fixed")
            run4 = make_run(root / "run4", 4, "random")
            run6 = make_run(root / "run6", 6, "random", later_character=".")
            output = root / "hash_result.txt"
            errors, passed = make_result(2, n1, run4, run6, output)
            self.assertEqual(errors, [])
            self.assertFalse(passed)
            self.assertIn("TOTAL 1/31 SAME -> FAIL", output.read_text(encoding="ascii"))

    def test_duplicate_distributed_n_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            n1 = make_run(root / "n1", 1, "fixed")
            run4a = make_run(root / "run4a", 4, "random", run_id="run4a")
            run4b = make_run(root / "run4b", 4, "random", run_id="run4b")
            output = root / "hash_result.txt"
            errors, passed = make_result(2, n1, run4a, run4b, output)
            self.assertFalse(passed)
            self.assertTrue(any("서로 달라야" in error for error in errors))
            self.assertFalse(output.exists())

    def test_invalid_statistics_do_not_write_pass(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            n1 = make_run(root / "n1", 1, "fixed")
            run4 = make_run(root / "run4", 4, "random")
            run6 = make_run(root / "run6", 6, "random")
            change_log(run4 / "logs" / "Assigner.txt", "BARRIER",
                       {"normal_bytes": -1})
            output = root / "hash_result.txt"
            errors, passed = make_result(2, n1, run4, run6, output)
            self.assertFalse(passed)
            self.assertTrue(any("normal_bytes" in error for error in errors))
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

