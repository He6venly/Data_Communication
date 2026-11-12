import io
import threading
import unittest
from unittest.mock import patch

from src.crasher.controller import PlayerController, PlayerState
from src.crasher.scheduler import CrashEvent, CrashScheduler


class FakeController:
    def __init__(self):
        self.condition = threading.Condition()
        self.players = {player: PlayerState(None) for player in range(1, 11)}
        self.players[1].mode = "PLAYING"
        self.players[1].mid = 7
        self.players[2].mode = "PLAYING"
        self.players[2].mid = 7
        self.error = None
        self.commands = []
        self.logs = []

    # 테스트에서는 명령을 받자마자 Player의 ACK 상태로 바꾼다.
    def send(self, player, command):
        self.commands.append((player, command))
        with self.condition:
            if command == "CRASH":
                self.players[player].mode = "CRASHED"
            elif command == "RESTART":
                self.players[player].mode = "IDLE"
                self.players[player].mid = None
            elif command == "QUIT":
                self.players[player].mode = "QUIT"
                self.players[player].mid = None
            self.condition.notify_all()

    def log(self, event, status, message):
        self.logs.append((event, status, message))

    def wait_for(self, predicate):
        with self.condition:
            self.condition.wait_for(predicate, timeout=1)
            if not predicate():
                raise TimeoutError("test state did not change")

    def finished_matches(self):
        return 0


class CrasherTests(unittest.TestCase):
    def test_ctrl_and_state_validation(self):
        logs = []
        controller = PlayerController(lambda *parts: logs.append(parts))
        controller.players[3] = PlayerState(None)
        self.assertEqual(controller.read_ctrl(io.BytesIO(b"CTRL P3\n")), 3)

        controller.update_state(3, ["STATE", "P3", "PLAYING", "18"])
        self.assertEqual((controller.players[3].mode, controller.players[3].mid), ("PLAYING", 18))
        controller.update_state(3, ["STATE", "P3", "IDLE"])
        self.assertEqual(controller.players[3].idle_count, 1)
        with self.assertRaises(ValueError):
            controller.update_state(3, ["STATE", "P3", "PLAYING"])

    def test_same_seed_makes_same_valid_plan(self):
        first = CrashScheduler(FakeController(), 11)
        second = CrashScheduler(FakeController(), 11)
        self.assertEqual(first.events, second.events)
        self.assertIn(len(first.events), range(4, 8))
        quit_count = sum(event.kind == "QUIT" for event in first.events)
        self.assertIn(quit_count, (1, 2))
        self.assertEqual([event.trigger for event in first.events], sorted(event.trigger for event in first.events))

    @patch("src.crasher.scheduler.time.sleep", return_value=None)
    def test_crash_ack_restart_and_idle(self, _sleep):
        controller = FakeController()
        scheduler = CrashScheduler(controller, 11)
        scheduler.events = [CrashEvent("CRASH", 2)]
        scheduler.random.choice = lambda players: 1
        scheduler.random.uniform = lambda start, end: 4.25 if start == 4 else 0

        self.assertTrue(scheduler.fire_event(1, scheduler.events[0]))
        for thread in scheduler.restart_threads:
            thread.join(timeout=1)

        self.assertEqual(controller.commands, [(1, "CRASH"), (1, "RESTART")])
        self.assertEqual(controller.players[1].mode, "IDLE")
        self.assertNotIn(1, scheduler.faulty)
        self.assertEqual([entry[0] for entry in controller.logs], ["CRASH", "CRASH_ACK", "RESTART", "REJOINED"])

    @patch("src.crasher.scheduler.time.sleep", return_value=None)
    def test_quit_stays_in_faulty_set(self, _sleep):
        controller = FakeController()
        scheduler = CrashScheduler(controller, 7)
        event = CrashEvent("QUIT", 3)
        scheduler.random.choice = lambda players: 2
        scheduler.random.uniform = lambda start, end: 0

        self.assertTrue(scheduler.fire_event(1, event))
        self.assertEqual(controller.commands, [(2, "QUIT")])
        self.assertIn(2, scheduler.faulty)
        self.assertIn(2, scheduler.pending)
        self.assertEqual(controller.logs[-1][0], "QUIT_ACK")


if __name__ == "__main__":
    unittest.main()
