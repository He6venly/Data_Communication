# Launcher 메시지 처리·종료·실행 인자를 테스트한다.

import argparse
import selectors
import socket
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock, patch

from hw3.common.protocol import Message, encode
from hw3.launcher.__main__ import Launcher, LauncherConfig, build_parser, parse_coord


class MessageHandlingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.launcher = object.__new__(Launcher)
        self.launcher.controller = __import__(
            "hw3.launcher.chaos", fromlist=["ChaosController"]
        ).ChaosController(seed=1)
        self.records = []

        class Logger:
            def write(inner_self, event, status, fields):
                self.records.append((event, status, fields))

        self.launcher.logger = Logger()

    def test_fragmented_ready_and_rejoined_are_parsed(self) -> None:
        slot = self.launcher.controller.workers[1]
        data = (encode(Message("READY", ("1",))) + "\n").encode()
        self.assertEqual([], slot.line_buffer.feed(data[:3]))
        for line in slot.line_buffer.feed(data[3:]):
            self.launcher._handle_message(1, line)
        self.assertTrue(slot.ready)

        from hw3.launcher.chaos import WorkerStatus

        slot.status = WorkerStatus.REJOINING
        data = b"REJOIN" + b"ED 1\n"
        for line in slot.line_buffer.feed(data[:4]):
            self.launcher._handle_message(1, line)
        for line in slot.line_buffer.feed(data[4:]):
            self.launcher._handle_message(1, line)
        self.assertEqual(WorkerStatus.RUNNING, slot.status)

    def test_rejects_worker_id_from_wrong_socket(self) -> None:
        self.launcher._handle_message(1, "READY 2")
        self.assertFalse(self.launcher.controller.workers[1].ready)
        self.assertEqual("PROTOCOL", self.records[-1][0])

    def test_fake_worker_control_socket_smoke_without_coordinator(self) -> None:
        launcher_side, worker_side = socket.socketpair()
        self.addCleanup(launcher_side.close)
        self.addCleanup(worker_side.close)
        self.launcher.selector = selectors.DefaultSelector()
        self.addCleanup(self.launcher.selector.close)
        slot = self.launcher.controller.workers[1]
        slot.control_socket = launcher_side
        self.launcher.selector.register(launcher_side, selectors.EVENT_READ, 1)

        worker_side.sendall(b"REA")
        self.launcher._receive(1, launcher_side)
        self.assertFalse(slot.ready)
        worker_side.sendall(b"DY 1\n")
        self.launcher._receive(1, launcher_side)
        self.assertTrue(slot.ready)

    def test_eof_before_all_ready_is_startup_failure(self) -> None:
        launcher_side, worker_side = socket.socketpair()
        self.addCleanup(launcher_side.close)
        self.addCleanup(worker_side.close)
        self.launcher.selector = selectors.DefaultSelector()
        self.addCleanup(self.launcher.selector.close)
        slot = self.launcher.controller.workers[1]
        slot.control_socket = launcher_side
        self.launcher.selector.register(launcher_side, selectors.EVENT_READ, 1)
        worker_side.close()
        with self.assertRaises(RuntimeError):
            self.launcher._receive(1, launcher_side)


class CliTests(unittest.TestCase):
    def test_coord_validation_uses_fixed_port(self) -> None:
        self.assertEqual("example.com:4575", parse_coord("example.com:4575"))
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_coord("example.com:9000")
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_coord("missing-port")

    def test_worker_count_validation_is_available_to_main_parser(self) -> None:
        args = build_parser().parse_args(
            [
                "--coord",
                "host:4575",
                "--seed",
                "42",
                "--run-id",
                "run",
                "--log-dir",
                "logs/run",
            ]
        )
        self.assertEqual(10, args.workers)
        self.assertEqual(100, args.step_delay)


class CompletionTests(unittest.TestCase):
    def test_nonzero_worker_exit_is_not_successful_completion(self) -> None:
        launcher = object.__new__(Launcher)
        launcher.config = LauncherConfig("host:4575", 10, "127.0.0.1", 7000, 100, 42, "test", Path("logs"))
        from hw3.launcher.chaos import ChaosController
        launcher.controller = ChaosController(seed=42)
        launcher.logger = Mock()
        launcher.selector = Mock()
        launcher.processes = {}
        launcher._connect_controls = Mock()
        launcher._event_loop = Mock()
        processes = {i: Mock(pid=i) for i in range(1, 11)}
        for process in processes.values():
            process.poll.return_value = 0
            process.wait.return_value = 0
        processes[4].poll.return_value = 1
        processes[4].wait.return_value = 1
        with patch("hw3.launcher.__main__.start_workers", return_value=processes):
            with self.assertRaisesRegex(RuntimeError, "Worker 4"):
                launcher.run()
        launcher.logger.write.assert_any_call("TERMINATE", "FAIL", ANY)


if __name__ == "__main__":
    unittest.main()
