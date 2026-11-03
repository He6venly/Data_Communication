import sys
import unittest

from tools.launch_workers import launch, main


class LauncherTests(unittest.TestCase):
    def test_four_children_finish(self):
        code = launch(4, [sys.executable, "-c", "print('worker ok')"])
        self.assertEqual(code, 0)

    def test_child_failure_is_returned(self):
        code = launch(4, [sys.executable, "-c", "import sys; sys.exit(7)"])
        self.assertEqual(code, 7)

    def test_bad_count_and_empty_command(self):
        with self.assertRaises(ValueError):
            launch(3, [sys.executable, "-c", "pass"])
        with self.assertRaises(ValueError):
            launch(1, [])

    def test_cli_separator_is_removed(self):
        code = main(["--count", "1", "--", sys.executable, "-c", "print('ok')"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

