import sys
import unittest

from hw3.launcher.processes import build_worker_command, start_worker, start_workers


class FakeProcess:
    next_pid = 100

    def __init__(self, command, **kwargs) -> None:
        self.command = command
        self.kwargs = kwargs
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class ProcessTests(unittest.TestCase):
    def test_builds_worker_command(self) -> None:
        command = build_worker_command(
            3, "example.com:4575", "127.0.0.1", 7000, 100, "run-1", "logs/run-1"
        )
        self.assertEqual(sys.executable, command[0])
        self.assertEqual(["-m", "hw3.worker"], command[1:3])
        self.assertEqual("3", command[command.index("--id") + 1])
        self.assertEqual("7003", command[command.index("--peer-port") + 1])
        self.assertEqual("100", command[command.index("--step-delay") + 1])

    def test_start_worker_uses_shell_false_without_pipes(self) -> None:
        calls = []

        def factory(command, **kwargs):
            calls.append((command, kwargs))
            return FakeProcess(command, **kwargs)

        start_worker([sys.executable, "-m", "hw3.worker"], factory)
        self.assertEqual(False, calls[0][1]["shell"])
        self.assertNotIn("stdout", calls[0][1])
        self.assertNotIn("stderr", calls[0][1])

    def test_starts_ten_workers_with_distinct_ports(self) -> None:
        calls = []

        def factory(command, **kwargs):
            calls.append(command)
            return FakeProcess(command, **kwargs)

        processes = start_workers(
            10, "host:4575", "127.0.0.1", 7000, 100, "run", "logs", factory
        )
        self.assertEqual(set(range(1, 11)), set(processes))
        ports = [command[command.index("--peer-port") + 1] for command in calls]
        self.assertEqual([str(port) for port in range(7001, 7011)], ports)

    def test_partial_start_failure_cleans_up_started_processes(self) -> None:
        started = []

        def factory(command, **kwargs):
            if len(started) == 3:
                raise OSError("cannot start worker")
            process = FakeProcess(command, **kwargs)
            process.terminated = False
            started.append(process)
            return process

        with self.assertRaises(OSError):
            start_workers(10, "host:4575", "127.0.0.1", 7000, 100, "run", "logs", factory)
        self.assertTrue(all(process.terminated for process in started))


if __name__ == "__main__":
    unittest.main()
