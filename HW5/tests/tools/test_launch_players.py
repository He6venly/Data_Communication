import tempfile
import unittest
from pathlib import Path

from tools.launch_players import build_commands, read_config


class LaunchPlayersTests(unittest.TestCase):
    def write_config(self, text):
        temp_root = Path(__file__).resolve().parents[2] / "tmp"
        temp_root.mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "players.txt"
        path.write_text(text, encoding="ascii", newline="\n")
        return path

    def test_read_standard_and_fault_config(self):
        lines = []
        for player in range(1, 11):
            fault = " slow@11,4" if player == 2 else ""
            lines.append(f"{player} RANDOM{fault}")
        configs = read_config(self.write_config("\n".join(lines) + "\n"))
        self.assertEqual(len(configs), 10)
        self.assertEqual(configs[1].fault, "slow@11,4")

    def test_reject_duplicate_or_unknown_strategy(self):
        duplicate = "\n".join(["1 RANDOM"] * 10)
        with self.assertRaisesRegex(ValueError, "P1..P10"):
            read_config(self.write_config(duplicate))

        lines = [f"{player} RANDOM" for player in range(1, 11)]
        lines[4] = "5 UNKNOWN"
        with self.assertRaisesRegex(ValueError, "unknown strategy"):
            read_config(self.write_config("\n".join(lines)))

    def test_build_ten_independent_commands(self):
        configs = read_config(self.write_config("\n".join(f"{player} RANDOM" for player in range(1, 11))))
        commands = build_commands(configs, "10.0.0.1", 9500, "18,22", "D", Path("logs"), "127.0.0.1:9700")
        self.assertEqual(len(commands), 10)
        self.assertEqual([command[command.index("--id") + 1] for command in commands], [str(i) for i in range(1, 11)])
        self.assertTrue(all(command[-2:] == ["--crasher", "127.0.0.1:9700"] for command in commands))


if __name__ == "__main__":
    unittest.main()
