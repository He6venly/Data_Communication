import unittest

from hw3.launcher.chaos import ChaosController, WorkerStatus


class RecordingRng:
    def __init__(self, uniforms, victims) -> None:
        self.uniforms = iter(uniforms)
        self.victims = iter(victims)
        self.calls = []

    def uniform(self, low, high):
        self.calls.append(("uniform", low, high))
        value = next(self.uniforms)
        if not low <= value <= high:
            raise AssertionError("test RNG value is outside requested range")
        return value

    def choice(self, candidates):
        candidates = tuple(candidates)
        self.calls.append(("choice", candidates))
        value = next(self.victims)
        if value not in candidates:
            raise AssertionError("test victim is not eligible")
        return value


def ready_all(controller: ChaosController, now: float = 100.0) -> None:
    for worker_id in range(1, 11):
        controller.mark_ready(worker_id, now)


class ChaosTests(unittest.TestCase):
    def test_t0_only_after_tenth_ready_and_initial_interval(self) -> None:
        rng = RecordingRng([12.0], [])
        controller = ChaosController(rng=rng)
        for worker_id in range(1, 10):
            self.assertFalse(controller.mark_ready(worker_id, 100.0))
            self.assertIsNone(controller.t0)
        self.assertTrue(controller.mark_ready(10, 100.0))
        self.assertEqual(100.0, controller.t0)
        self.assertEqual(112.0, controller.next_crash)
        self.assertEqual([("uniform", 10.0, 20.0)], rng.calls)

    def test_random_call_order_and_ranges(self) -> None:
        rng = RecordingRng([12.0, 11.0, 7.0], [4])
        controller = ChaosController(rng=rng)
        ready_all(controller)
        plan = controller.due_crash(112.0)
        self.assertEqual(4, plan.worker_id)
        self.assertEqual(11.0, plan.downtime)
        self.assertEqual(123.0, plan.restart_at)
        self.assertEqual(119.0, controller.next_crash)
        self.assertEqual(
            [
                ("uniform", 10.0, 20.0),
                ("choice", tuple(range(1, 11))),
                ("uniform", 10.0, 15.0),
                ("uniform", 5.0, 15.0),
            ],
            rng.calls,
        )

    def test_only_running_worker_is_selected(self) -> None:
        rng = RecordingRng([10.0, 10.0, 5.0], [3])
        controller = ChaosController(rng=rng)
        ready_all(controller, 0.0)
        controller.workers[1].status = WorkerStatus.EXITED
        controller.workers[2].status = WorkerStatus.REJOINING
        plan = controller.due_crash(10.0)
        self.assertNotIn(1, plan.candidates)
        self.assertNotIn(2, plan.candidates)
        self.assertEqual(3, plan.worker_id)

    def test_two_down_blocks_interval_until_rejoined(self) -> None:
        rng = RecordingRng([10.0, 10.0, 5.0, 10.0, 6.0], [1, 2])
        controller = ChaosController(rng=rng)
        ready_all(controller, 0.0)
        controller.due_crash(10.0)
        second = controller.due_crash(15.0)
        self.assertEqual(2, second.worker_id)
        self.assertEqual((1, 2), controller.down_workers)
        self.assertIsNone(controller.next_crash)
        self.assertTrue(controller.blocked)
        self.assertEqual(6, len(rng.calls))
        self.assertEqual(("uniform", 10.0, 15.0), rng.calls[-1])

        self.assertEqual([1], controller.due_restarts(20.0))
        self.assertEqual(WorkerStatus.REJOINING, controller.workers[1].status)
        self.assertTrue(controller.mark_rejoined(1, 21.0))
        self.assertEqual(27.0, controller.next_crash)
        self.assertEqual((2,), controller.down_workers)
        self.assertEqual(("uniform", 5.0, 15.0), rng.calls[-1])

    def test_state_transitions_and_repeat_victim(self) -> None:
        rng = RecordingRng([10.0, 10.0, 5.0, 10.0, 5.0], [4, 4])
        controller = ChaosController(rng=rng)
        ready_all(controller, 0.0)
        controller.due_crash(10.0)
        self.assertEqual(WorkerStatus.CRASHED, controller.workers[4].status)
        self.assertEqual([4], controller.due_restarts(20.0))
        self.assertEqual(WorkerStatus.REJOINING, controller.workers[4].status)
        self.assertTrue(controller.mark_rejoined(4, 20.1))
        controller.next_crash = 25.0
        plan = controller.due_crash(25.0)
        self.assertEqual(4, plan.worker_id)
        self.assertEqual(2, plan.crash_count)

    def test_no_new_crash_at_or_after_cutoff(self) -> None:
        rng = RecordingRng([20.0], [])
        controller = ChaosController(rng=rng)
        ready_all(controller, 100.0)
        controller.next_crash = 180.0
        self.assertIsNone(controller.due_crash(180.0))
        self.assertTrue(controller.injection_finished)

    def test_eof_exits_and_cancels_restart(self) -> None:
        rng = RecordingRng([10.0, 12.0, 5.0], [1])
        controller = ChaosController(rng=rng)
        ready_all(controller, 0.0)
        controller.due_crash(10.0)
        self.assertIsNotNone(controller.workers[1].restart_at)
        controller.mark_exited(1)
        self.assertEqual(WorkerStatus.EXITED, controller.workers[1].status)
        self.assertIsNone(controller.workers[1].restart_at)
        self.assertEqual([], controller.due_restarts(30.0))
        for worker_id in range(2, 11):
            controller.mark_exited(worker_id)
        self.assertTrue(controller.all_exited)


if __name__ == "__main__":
    unittest.main()
