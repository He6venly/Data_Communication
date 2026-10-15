import json
from pathlib import Path
import tempfile
import unittest

from hw3.tools.verify_logs import verify


class LogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = {"Coordinator": [], "Launcher": [], **{f"Worker{i}": [] for i in range(1, 11)}}
        self.seq = 0
        self.add("Coordinator", "INIT", dispatchers=6, task_locks=1000, workers=10)
        for i in range(1, 11):
            self.add("Coordinator", "HELLO", worker=i)
            self.add("Coordinator", "RING_OK", worker=i)
            self.add(f"Worker{i}", "INIT")
            self.add("Launcher", "READY", worker=i)
        self.rows["Launcher"].insert(0, self.row("Launcher", "INIT"))
        self.add("Coordinator", "START", ring_ready=10)
        for k in range(1000):
            value = 5761455 if k == 0 else 0  # Synthetic log fixture, not measured prime results.
            self.add("Coordinator", "ASSIGN", task=k, epoch=1, worker=1, rejoin_count=0)
            self.add("Worker1", "RESULT", task=k, epoch=1, result=value)
            self.add("Coordinator", "COMMIT", task=k, epoch=1, worker=1, result=value,
                     commit_count=1, rejoin_count=0)
        self.add("Coordinator", "VERIFY", **{"pass": True, "done": 1000, "commits": 1000,
                                               "double_commit": 0, "sum": 5761455, "all_commit_once": True})
        self.add("Coordinator", "TERMINATE", threads_alive=0)
        for i in range(1, 11):
            self.add(f"Worker{i}", "TERMINATE", threads_alive=0)
            self.add("Launcher", "EOF", worker=i, down=[])
        self.add("Launcher", "TERMINATE")

    def row(self, node, event, **fields):
        if node == "Coordinator":
            self.seq += 1
            fields = {"seq": self.seq, "elapsed_ms": self.seq, **fields}
        return {"event": event, "status": "SUCCESS", "run_id": "fixture", "ts_unix_ms": 100000, **fields}

    def add(self, node, event, **fields):
        self.rows[node].append(self.row(node, event, **fields))

    def check(self):
        for node, rows in self.rows.items():
            label = "COORD" if node == "Coordinator" else node.upper() if node == "Launcher" else node
            with (self.root/f"{node}.txt").open("w", encoding="utf-8") as stream:
                for r in rows:
                    r = dict(r)
                    event, status = r.pop("event"), r.pop("status")
                    stream.write(f"[09:00:00.000] {label} | {event} | {status} | "+json.dumps(r)+"\n")
        return verify(self.root, "fixture", allow_no_crashes=True)

    def test_complete_development_run_and_seq_order_not_file_order(self):
        # Writes from different dispatcher threads can reach the logger out of order.
        self.rows["Coordinator"][25:40] = reversed(self.rows["Coordinator"][25:40])
        report = self.check()
        self.assertTrue(report["pass"], report["errors"])
        self.assertFalse(report["deployment_verified"])

    def test_duplicate_commit_detected_even_when_verify_claims_pass(self):
        commit = next(r for r in self.rows["Coordinator"] if r["event"] == "COMMIT")
        self.add("Coordinator", "COMMIT", **{k: v for k, v in commit.items()
                                           if k not in {"event", "status", "seq", "run_id", "ts_unix_ms"}})
        self.assertFalse(self.check()["pass"])

    def test_stale_owner_or_epoch_commit_rejected(self):
        commit = next(r for r in self.rows["Coordinator"] if r["event"] == "COMMIT")
        commit["epoch"] = 2
        self.assertIn("COMMIT does not match current epoch/owner", self.check()["errors"])

    def test_missing_worker_result_is_not_complete_evidence(self):
        self.rows["Worker1"] = [r for r in self.rows["Worker1"] if r["event"] != "RESULT"]
        self.assertFalse(self.check()["pass"])

    def test_mixed_run_ids_rejected(self):
        self.rows["Worker10"][0]["run_id"] = "other"
        self.assertFalse(self.check()["pass"])

    def test_three_concurrent_crashes_rejected(self):
        for i in range(1, 4):
            # Insert before EOF events, preserving the Launcher's actual event order.
            self.rows["Launcher"].insert(10+i, self.row("Launcher", "CRASH", worker=i,
                                                       crash_count=1, down=list(range(1, i+1))))
        self.assertIn("Launcher concurrent CRASHED+REJOINING exceeds two", self.check()["errors"])

    def test_missing_file_and_truncated_line_rejected(self):
        self.check()
        (self.root/"Worker10.txt").unlink()
        self.assertFalse(verify(self.root)["pass"])
        (self.root/"Worker10.txt").write_text("[partial", encoding="utf-8")
        self.assertFalse(verify(self.root)["pass"])

    def test_no_crash_requires_explicit_development_option(self):
        self.assertTrue(self.check()["pass"])
        self.assertFalse(verify(self.root)["pass"])

    def retakeover_fixture(self):
        original = self.rows["Coordinator"]
        prefix = original[:next(i for i, r in enumerate(original) if r["event"] == "ASSIGN")]
        rows = list(prefix)
        def event(kind, elapsed, **fields):
            rows.append(self.row("Coordinator", kind, elapsed_ms=elapsed, **fields))
        event("ASSIGN", 0, task=0, epoch=1, worker=1, rejoin_count=0)
        for source, target, epoch, at in ((1, 2, 2, 5000), (2, 3, 3, 10000)):
            event("DEAD", at, worker=source, crash_count=1, owned_tasks=[0], to_worker=target,
                  last_hb_elapsed_ms=at-5000, detection_delay_ms=5000, dead_now=list(range(1, source+1)))
            event("TAKEOVER", at, task=0, old_epoch=epoch-1, epoch=epoch,
                  from_worker=source, to_worker=target)
            event("DEAD_SCAN", at, worker=source, crash_count=1, owned_tasks=[0])
        for worker in (1, 2):
            event("REJOIN", 11000+worker, worker=worker, rejoin_count=1)
        event("COMMIT", 12000, task=0, epoch=3, worker=3, result=5761455, commit_count=1, rejoin_count=0)
        for r in original[len(prefix):]:
            if r.get("task") == 0:
                continue
            r = dict(r)
            if r["event"] in {"ASSIGN", "COMMIT"}:
                r["worker"] = 2 if r["task"] == 2 else 1
                r["rejoin_count"] = 1
            r["elapsed_ms"] += 13000
            rows.append(r)
        for i, r in enumerate(rows, 1):
            r["seq"] = i
        self.rows["Coordinator"] = rows
        results = [r for r in self.rows["Worker1"] if r["event"] == "RESULT"]
        self.rows["Worker1"] = [r for r in self.rows["Worker1"] if r.get("task") not in (0, 2)]
        self.rows["Worker3"].insert(1, self.row("Worker3", "RESULT", task=0, epoch=3, result=5761455))
        self.rows["Worker2"].insert(1, next(r for r in results if r["task"] == 2))
        self.rows["Launcher"] = [self.row("Launcher", "INIT")]
        for i in range(1, 11):
            self.add("Launcher", "READY", worker=i)
        self.add("Launcher", "CRASH", worker=1, crash_count=1, down=[1])
        self.add("Launcher", "CRASH", worker=2, crash_count=1, down=[1, 2])
        for i in (1, 2):
            self.add("Launcher", "RESTART", worker=i, down=[i, 2] if i == 1 else [2])
            self.add("Launcher", "REJOINED", worker=i, down=[2] if i == 1 else [])
        for i in range(1, 11):
            self.add("Launcher", "EOF", worker=i, down=[])
        self.add("Launcher", "TERMINATE")

    def test_retakeover_recovery_tracks_the_final_commit_and_missing_resume_is_zero(self):
        self.retakeover_fixture()
        report = self.check()
        self.assertTrue(report["pass"], report["errors"])
        self.assertEqual([r["recovery_ms"] for r in report["faults"]], [7000, 2000])
        self.assertEqual([r["ckpt_saving"] for r in report["faults"]], [0, 0])

    def test_dead_scan_detects_task_omitted_from_both_owned_list_and_takeover(self):
        self.retakeover_fixture()
        rows = self.rows["Coordinator"]
        self.rows["Coordinator"] = [r for r in rows if r["event"] != "TAKEOVER"]
        for r in self.rows["Coordinator"]:
            if r["event"] in {"DEAD", "DEAD_SCAN"}:
                r["owned_tasks"] = []
            if r["event"] == "COMMIT" and r.get("task") == 0:
                r.update(worker=1, epoch=1, rejoin_count=1)
        self.rows["Worker3"] = [r for r in self.rows["Worker3"] if r.get("task") != 0]
        self.rows["Worker1"].insert(1, self.row("Worker1", "RESULT", task=0, epoch=1, result=5761455))
        self.assertIn("DEAD ownership scan omitted an unfinished task", self.check()["errors"])

    def test_takeover_requires_its_dead_event(self):
        self.retakeover_fixture()
        self.rows["Coordinator"] = [r for r in self.rows["Coordinator"]
                                    if not (r["event"] == "DEAD" and r.get("worker") == 1)]
        self.assertIn("TAKEOVER outside its DEAD ownership scan", self.check()["errors"])

    def test_inflight_result_committed_before_dead_scan_is_not_an_omission(self):
        self.retakeover_fixture()
        rows = [r for r in self.rows["Coordinator"] if r["event"] != "TAKEOVER"]
        commit = next(r for r in rows if r["event"] == "COMMIT" and r.get("task") == 0)
        rows.remove(commit)
        commit.update(worker=1, epoch=1, rejoin_count=0, elapsed_ms=5001)
        position = next(i for i, r in enumerate(rows) if r["event"] == "DEAD_SCAN")
        rows.insert(position, commit)
        for seq, r in enumerate(rows, 1):
            r["seq"] = seq
            if r["event"] in {"DEAD", "DEAD_SCAN"}:
                r["owned_tasks"] = []
        self.rows["Coordinator"] = rows
        self.rows["Worker3"] = [r for r in self.rows["Worker3"] if r.get("task") != 0]
        self.rows["Worker1"].insert(1, self.row("Worker1", "RESULT", task=0, epoch=1, result=5761455))
        report = self.check()
        self.assertTrue(report["pass"], report["errors"])

    def test_approved_rejoin_cannot_omit_launcher_restart_and_confirmation(self):
        self.retakeover_fixture()
        self.rows["Launcher"] = [r for r in self.rows["Launcher"]
                                 if not (r["event"] in {"RESTART", "REJOINED"} and r.get("worker") == 1)]
        self.assertIn("per-worker CRASH, DEAD and approved REJOIN counts differ", self.check()["errors"])

    def test_assignment_cannot_precede_approved_rejoin(self):
        self.retakeover_fixture()
        rows = self.rows["Coordinator"]
        rejoin = next(r for r in rows if r["event"] == "REJOIN" and r.get("worker") == 1)
        rows.remove(rejoin)
        position = next(i for i, r in enumerate(rows) if r["event"] == "ASSIGN" and r.get("rejoin_count") == 1)
        rows.insert(position+1, rejoin)
        for seq, r in enumerate(rows, 1):
            r["seq"] = seq
        self.assertIn("ASSIGN before approved REJOIN or with wrong rejoin cycle", self.check()["errors"])

    def test_dead_timeout_uses_timestamps_instead_of_claimed_delay(self):
        self.retakeover_fixture()
        dead = next(r for r in self.rows["Coordinator"] if r["event"] == "DEAD")
        dead["last_hb_elapsed_ms"] = dead["elapsed_ms"]-4999
        self.assertIn("DEAD was declared before the heartbeat timeout", self.check()["errors"])

    def test_payload_cannot_override_envelope_identity(self):
        self.rows["Worker1"][0]["node"] = "Worker2"
        self.assertFalse(self.check()["pass"])


if __name__ == "__main__":
    unittest.main()
