# 소수 계산과 Worker 상태 전이를 테스트한다.

import threading
import unittest

from hw3.worker.primes import count_step, small_primes, step_bounds
from hw3.worker.state import Assignment, Checkpoint, WorkerState


class PrimeTests(unittest.TestCase):
    def test_base_and_inclusive_ranges(self):
        self.assertEqual((len(small_primes()), small_primes()[-1]), (1229, 9973))
        self.assertEqual(step_bounds(0, 1), (1, 10000))
        self.assertEqual(step_bounds(999, 10), (99990001, 100000000))
        for task, step in ((-1, 1), (1000, 1), (0, 0), (0, 11)):
            with self.assertRaises(ValueError):
                step_bounds(task, step)

    def test_task_zero_step_cumulative_against_independent_sieve(self):
        flags = [True] * 100001
        flags[0] = flags[1] = False
        for p in range(2, 317):
            if flags[p]:
                for number in range(p * p, 100001, p):
                    flags[number] = False
        partial = 0
        for step in range(1, 11):
            partial += count_step(0, step)
            self.assertEqual(partial, sum(flags[:step * 10000 + 1]))
        self.assertEqual(partial, 9592)

    def test_official_task_samples(self):
        for task, expected in ((152, 6075), (160, 5989), (271, 5802)):
            self.assertEqual(sum(count_step(task, s) for s in range(1, 11)), expected)

    def test_full_1000_task_total(self):
        self.assertEqual(sum(count_step(k, s) for k in range(1000) for s in range(1, 11)), 5761455)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = WorkerState()
        self.state.start()

    def tearDown(self):
        self.state.stop()

    def test_store_orders_epoch_then_step_and_takeover_resumes(self):
        self.assertTrue(self.state.save_checkpoint(152, Checkpoint(1, 8, 4800)))
        self.assertFalse(self.state.save_checkpoint(152, Checkpoint(1, 7, 4700)))
        self.assertTrue(self.state.save_checkpoint(152, Checkpoint(2, 2, 1200)))
        self.assertFalse(self.state.save_checkpoint(152, Checkpoint(1, 9, 5400)))
        self.state.enqueue(Assignment(152, 3, 4))
        work = self.state.take_work()
        self.assertEqual((work.resume_step, work.partial, work.ckpt_epoch), (3, 1200, 2))

    def test_crash_clears_everything_and_stale_handler_generation_is_rejected(self):
        self.state.enqueue(Assignment(0, 1))
        work = self.state.take_work()
        self.state.enqueue(Assignment(152, 2, 4))
        self.state.save_checkpoint(271, Checkpoint(1, 5, 3000))
        self.state.requested = self.state.no_task = True
        self.state.crash()
        self.assertEqual(self.state.mode, "CRASHED")
        self.assertFalse(self.state.queue or self.state.store or self.state.latest or self.state.current)
        self.assertFalse(self.state.requested or self.state.no_task or self.state.valid(work))
        self.assertFalse(self.state.save_checkpoint(0, Checkpoint(1, 1, 1229)))
        self.assertFalse(self.state.enqueue(Assignment(0, 1)))
        self.state.restart()
        self.assertTrue(self.state.save_checkpoint(0, Checkpoint(1, 1, 1229)))
        self.state.welcome()
        self.assertFalse(self.state.enqueue(Assignment(0, 1), generation=0))
        self.state.mark_no_task(generation=0)
        self.assertFalse(self.state.no_task)

    def test_rejoining_queues_takeovers_but_rejects_assign_and_old_generation(self):
        self.state.crash()
        self.state.restart()
        self.assertFalse(self.state.enqueue(Assignment(0, 1)))
        self.assertFalse(self.state.enqueue(Assignment(0, 2, 4), generation=0))
        self.assertTrue(self.state.enqueue(Assignment(0, 2, 4), generation=1))
        self.assertFalse(self.state.enqueue(Assignment(0, 2, 4), generation=1))
        self.assertTrue(self.state.enqueue(Assignment(152, 2, 4), generation=1))
        self.assertEqual([a.task for a in self.state.queue], [0, 152])
        self.assertIsNone(self.state.current)
        self.assertFalse(self.state.requested)
        self.state.welcome()
        self.assertEqual(self.state.take_work().assignment.task, 0)
        self.assertEqual(self.state.take_work().assignment.task, 152)

    def test_current_then_fifo_and_no_task_persists(self):
        self.state.enqueue(Assignment(0, 1))
        first = self.state.take_work()
        self.state.mark_no_task()
        for task in (160, 152):
            self.state.enqueue(Assignment(task, 2, 4))
        self.assertTrue(self.state.valid(first))
        self.state.finish(first)
        self.assertEqual(self.state.take_work().assignment.task, 160)
        self.assertEqual(self.state.take_work().assignment.task, 152)
        self.assertTrue(self.state.no_task)

    def test_duplicate_and_newer_assignment_invalidates_older_work(self):
        self.state.enqueue(Assignment(0, 1))
        work = self.state.take_work()
        self.assertFalse(self.state.enqueue(Assignment(0, 1)))
        self.state.enqueue(Assignment(0, 3, 10))
        self.assertFalse(self.state.valid(work))
        self.assertFalse(self.state.enqueue(Assignment(0, 2, 4)))
        self.assertEqual(len(self.state.queue), 1)

    def test_bye_wakes_compute_while_crashed(self):
        self.state.crash()
        result = []
        thread = threading.Thread(target=lambda: result.append(self.state.take_work()))
        thread.start()
        self.state.stop()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [None])


if __name__ == "__main__":
    unittest.main()
