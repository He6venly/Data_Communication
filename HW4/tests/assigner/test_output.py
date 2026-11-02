import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.assigner.barrier import RoundMeasurement
from src.assigner.log import AssignerLog
from src.assigner.metrics import Metrics
from src.assigner.storage import RunStorage


class OutputTests(unittest.TestCase):
    def test_snapshots_hashes_and_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            saved = []
            storage = RunStorage(root, {"run_id": "test"}, saved.append)
            rows = (" " * 159 + ".",) * 80
            for state in range(0, 3001, 10):
                storage.save_snapshot(state, rows)
            data = ("\n".join(rows) + "\n").encode("ascii")
            hash8 = hashlib.sha256(data).hexdigest()[:8]
            hashes = (root / "RoundHash.txt").read_text(encoding="ascii").splitlines()
            self.assertEqual(len(hashes), 31)
            self.assertEqual(hashes[0], f"round0000.txt {hash8}")
            self.assertEqual(hashes[-1], f"round3000.txt {hash8}")
            self.assertEqual(len(list((root / "frames").glob("frame*.txt"))), 301)
            self.assertEqual((root / "round3000.txt").read_bytes(), data)
            self.assertEqual(len(saved), 332)
            self.assertEqual(saved[0]["bytes"], 12880)
            self.assertEqual(saved[0]["hash8"], hash8)
            with self.assertRaises(FileExistsError):
                RunStorage(root, {})
            with self.assertRaises(ValueError):
                storage.save_snapshot(3000, rows)

    def test_log_format_and_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Assigner.txt"
            log = AssignerLog(path, "run-1")
            line = log.write("SAVE", "SUCCESS", state_round=0, bytes=12880)
            log.close()
            self.assertEqual(path.read_bytes(), (line + "\n").encode())
            self.assertRegex(line, r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\] ASSIGNER \| SAVE \| SUCCESS \| ")
            self.assertEqual(json.loads(line.split(" | ")[-1])["run_id"], "run-1")
            with self.assertRaises(FileExistsError):
                AssignerLog(path, "run-2")
        metrics = Metrics(4)
        summaries = []
        for r in range(3000):
            summary = metrics.add(RoundMeasurement(r, 2, 1, r % 4, 100, (r + 1) % 10 == 0))
            if summary is not None:
                summaries.append(summary)
        self.assertEqual(len(summaries), 30)
        self.assertEqual((summaries[0]["normal_rounds"], summaries[0]["full_rounds"]), (90, 10))
        final = metrics.finish(6000, 4)
        self.assertEqual(final["throughput_round_s"], 500)
        self.assertEqual(final["slowest_workers"], [0, 1, 2, 3])
        self.assertEqual((final["normal_bytes"], final["full_bytes"]), (270000, 30000))


if __name__ == "__main__":
    unittest.main()
