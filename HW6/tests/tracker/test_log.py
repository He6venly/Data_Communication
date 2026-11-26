from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import time
import unittest

from src.common.contracts import LifecycleError
from src.tracker.log import EventLog


class LogTests(unittest.TestCase):
    def test_concurrent_json_lines_and_terminal_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = EventLog(peer_id="tracker", root=root, started_at=time.monotonic())
            try:
                log.event("START_PROGRAM", env="DEV", run="A", port=6000)

                def emit(worker):
                    for n in range(40):
                        log.event("JOIN", id=f"P{worker}", n=n)

                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(emit, range(8)))
                # close 없이 즉시 읽어 flush와 JSON 줄 경계를 검사함.
                rows = [json.loads(x) for x in (root / "logs/tracker.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(rows), 321)
                self.assertEqual([x["t"] for x in rows], sorted(x["t"] for x in rows))
                log.event("EXIT", code=0)
                with self.assertRaises(LifecycleError):
                    log.event("LATE")
                self.assertEqual(log.recent(0), ())
                self.assertTrue(log.recent()[-1].find("EXIT") >= 0)
            finally:
                log.close()
                log.close()
            raw = (root / "logs/tracker.jsonl").read_bytes()
            self.assertNotIn(b"\r\n", raw)
            self.assertEqual(json.loads(raw.splitlines()[-1])["ev"], "EXIT")
            with self.assertRaises(LifecycleError):
                log.event("LATE")

    def test_invalid_fields_do_not_write_partial_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = EventLog(peer_id="tracker", root=root, started_at=time.monotonic())
            try:
                for fields in ({"peer": "wrong"}, {"t": 2}, {"x": float("nan")}, {"x": object()}):
                    with self.subTest(fields=fields), self.assertRaises((ValueError, TypeError)):
                        log.event("BAD", **fields)
                log.event("JOIN", id="한글", ok=True, absent=None)
                rows = (root / "logs/tracker.jsonl").read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(rows), 1)
                self.assertEqual(json.loads(rows[0])["id"], "한글")
            finally:
                log.close()
