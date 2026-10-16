import threading
import unittest
from types import SimpleNamespace

from hw3.coordinator.tables import Tables


class TablesTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.tables = Tables(lambda: self.now)
        for i in range(1, 11):
            self.tables.hello(SimpleNamespace(worker_id=None), i, "127.0.0.1", 7000+i)
        self.tables.phase = "RING"
        for i in range(1, 11):
            self.tables.ring_ok(i)
        self.tables.begin()
        self.tables.detector_enabled = True

    def alive_except(self, *dead):
        for i in range(1, 11):
            if i not in dead:
                self.tables.heartbeat(i)

    def test_locks_are_per_task_and_start_requires_all_ring_ok(self):
        self.assertEqual(len({id(t.lock) for t in self.tables.tasks}), 1000)
        with self.assertRaises(RuntimeError):
            Tables().begin()

    def test_suspect_hb_recovery_dead_and_ignored_dead_hb(self):
        self.now = 3
        self.alive_except(4)
        events, _ = self.tables.detect()
        self.assertEqual([r.kind for r in events], ["SUSPECT"])
        self.assertEqual(self.tables.workers[4].state, "SUSPECT")
        self.tables.heartbeat(4)
        self.assertEqual(self.tables.workers[4].state, "ALIVE")
        self.now = 8
        self.alive_except(4)
        self.tables.detect()
        self.assertEqual(self.tables.workers[4].state, "DEAD")
        self.assertEqual(self.tables.heartbeat(4), [])

    def test_rejection_order_and_current_epoch_owner(self):
        self.tables.request(4)
        self.assertEqual(self.tables.result(5, 0, 1, 1229)[0], ("REJECT_STALE", (0, "EPOCH")))
        self.assertEqual(self.tables.result(4, 0, 1, 9592)[0], ("ACK", (0,)))
        self.assertEqual(self.tables.result(4, 0, 1, 9592)[0], ("REJECT_STALE", (0, "DONE")))
        self.tables.workers[4].state = "DEAD"
        self.assertEqual(self.tables.result(4, 0, 1, 9592)[0], ("REJECT_STALE", (0, "DEAD")))

    def test_six_simultaneous_results_commit_once(self):
        self.tables.request(4)
        barrier = threading.Barrier(6)
        replies = []
        def submit():
            barrier.wait()
            replies.append(self.tables.result(4, 0, 1, 9592)[0])
        threads = [threading.Thread(target=submit) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(2)
            self.assertFalse(t.is_alive())
        self.assertEqual(sum(r[0] == "ACK" for r in replies), 1)
        self.assertEqual(self.tables.done_count, 1)
        self.assertEqual(self.tables.tasks[0].commit_count, 1)

    def test_adjacent_and_wraparound_retakeover_includes_queued_tasks(self):
        for source, neighbor, target in ((4, 5, 6), (10, 1, 2)):
            with self.subTest(source=source):
                self.setUp()
                self.tables.request(source)
                self.tables.request(neighbor)
                self.now = 5
                self.alive_except(source)
                self.tables.detect()
                self.assertEqual((self.tables.tasks[0].owner, self.tables.tasks[0].epoch), (neighbor, 2))
                self.now = 10
                self.alive_except(source, neighbor)
                events, actions = self.tables.detect()
                self.assertEqual([f[0] for f in actions], [target, target])
                self.assertEqual((self.tables.tasks[0].owner, self.tables.tasks[0].epoch), (target, 3))
                self.assertEqual((self.tables.tasks[1].owner, self.tables.tasks[1].epoch), (target, 2))
                self.assertEqual(next(e.fields["owned_tasks"] for e in events if e.kind == "DEAD"), [0, 1])

    def test_simultaneous_dead_marked_first_and_suspect_skipped(self):
        self.tables.request(4)
        self.tables.request(5)
        self.now = 5
        self.alive_except(4, 5)
        _, actions = self.tables.detect()
        self.assertEqual([a[0] for a in actions], [6, 6])
        self.assertEqual(self.tables.next_alive(4), 6)
        self.tables.workers[6].state = "SUSPECT"
        self.assertEqual(self.tables.next_alive(4), 7)
        for i, w in self.tables.workers.items():
            if i not in (4, 5):
                w.state = "SUSPECT"
        self.assertEqual(self.tables.next_alive(4), 6)

    def test_rejoin_retries_then_new_assignment_not_old_task(self):
        self.tables.request(4)
        self.assertEqual(self.tables.rejoin(4)[0][0], "RETRY_LATER")
        self.now = 5
        self.alive_except(4)
        self.tables.detect()
        self.now = 10
        self.assertEqual(self.tables.rejoin(4)[0][0], "WELCOME")
        reply, _ = self.tables.request(4)
        self.assertEqual(reply, ("ASSIGN", (1, 1)))
        self.assertEqual(self.tables.tasks[0].owner, 5)

    def test_request_and_fd_race_never_leaves_dead_owned_task(self):
        self.now = 5
        self.alive_except(4)
        barrier = threading.Barrier(2)
        def request():
            barrier.wait()
            self.tables.request(4)
        thread = threading.Thread(target=request)
        thread.start()
        barrier.wait()
        self.tables.detect()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(any(t.state == "ASSIGNED" and t.owner == 4 for t in self.tables.tasks))

    def test_final_verify_and_recovery_summary_use_final_task_commit(self):
        self.tables.request(4)
        self.now = 5
        self.alive_except(4)
        self.tables.detect()
        self.now = 6
        self.tables.result(5, 0, 2, 5761455)  # Synthetic accepted result for summary testing.
        self.now = 6.5
        self.tables.rejoin(4)
        self.now = 7
        for k in range(1, 1000):
            self.assertEqual(self.tables.request(4)[0], ("ASSIGN", (k, 1)))
            self.tables.result(4, k, 1, 0)
        self.assertTrue(self.tables.verify()["pass"])
        metrics = self.tables.metrics()
        self.assertEqual(metrics["faults"][0]["owned_tasks"], [0])
        self.assertEqual(metrics["faults"][0]["recovery_ms"], 1000)
        self.assertEqual(metrics["rejoins"][0]["latency_ms"], 500)
        self.assertEqual(metrics["rejoins"][0]["commits"], 999)


if __name__ == "__main__":
    unittest.main()
