# 로그 형식과 동시 기록을 테스트한다.

import json
import re
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path

from hw3.common.log import NodeLogger, _KST


LINE_RE = re.compile(
    r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\] LAUNCHER \| ([A-Z_]+) \| (SUCCESS|FAIL|INFO|WARN) \| (\{.*\})$"
)


class LoggerTests(unittest.TestCase):
    def test_kst_does_not_require_external_timezone_data(self) -> None:
        self.assertEqual(timedelta(hours=9), _KST.utcoffset(None))
        self.assertEqual("KST", _KST.tzname(None))

    def test_kst_json_format_and_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Launcher.txt"
            logger = NodeLogger("LAUNCHER", path, "run-1")
            logger.write("INIT", "INFO", {"contract_version": 1})
            logger.close()
            line = path.read_text(encoding="utf-8").strip()
            match = LINE_RE.match(line)
            self.assertIsNotNone(match)
            payload = json.loads(match.group(7))
            self.assertEqual("run-1", payload["run_id"])
            self.assertIsInstance(payload["ts_unix_ms"], int)
            self.assertEqual(1, payload["contract_version"])

    def test_concurrent_write_and_repeated_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Launcher.txt"
            logger = NodeLogger("LAUNCHER", path, "run-2")
            threads = [
                threading.Thread(
                    target=logger.write,
                    args=("READY", "SUCCESS", {"worker": worker}),
                )
                for worker in range(1, 11)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            logger.close()
            logger.close()
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(10, len(lines))
            workers = []
            for line in lines:
                match = LINE_RE.match(line)
                self.assertIsNotNone(match)
                payload = json.loads(match.group(7))
                self.assertEqual("run-2", payload["run_id"])
                workers.append(payload["worker"])
            self.assertCountEqual(range(1, 11), workers)

    def test_reserved_fields_and_write_after_close_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            logger = NodeLogger("LAUNCHER", Path(directory) / "x.txt", "run")
            with self.assertRaises(ValueError):
                logger.write("INIT", "INFO", {"run_id": "other"})
            logger.close()
            with self.assertRaises(ValueError):
                logger.write("INIT", "INFO", {})


if __name__ == "__main__":
    unittest.main()
