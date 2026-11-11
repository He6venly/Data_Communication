import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from src.player.bots import Bot, LCG, prize_order, team_choose


def kit_root():
    root = Path(os.environ.get("HW5_KIT_DIR", Path.cwd().parent / "HW5_student_kit"))
    if not (root / "1_bot_test_kit" / "bot_tests.txt").is_file():
        raise AssertionError("HW5_KIT_DIR must point to the original student kit")
    return root


def kit_module():
    path = kit_root() / "1_bot_test_kit/python/bot_test.py"
    spec = importlib.util.spec_from_file_location("official_bot_test", path)
    module = importlib.util.module_from_spec(spec)
    import src.player.bots as bots
    previous = sys.modules.get("mybots")
    sys.modules["mybots"] = bots
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            del sys.modules["mybots"]
        else:
            sys.modules["mybots"] = previous
    return module


class BotTests(unittest.TestCase):
    def test_official_41_cases(self):
        # 원본 키트는 그대로 두고 임시 복사본에서 내 bot을 연결해 확인함
        with tempfile.TemporaryDirectory(prefix="hw5 bot kit ") as directory:
            target = Path(directory) / "kit"
            shutil.copytree(kit_root() / "1_bot_test_kit", target)
            (target / "python/mybots.py").write_text("from src.player.bots import *\n", encoding="ascii")
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONIOENCODING": "utf-8"}
            result = subprocess.run([sys.executable, str(target / "python/bot_test.py")], cwd=target,
                                    env=env, capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count("[PASS]"), 41, result.stdout)
            self.assertNotIn("[FAIL]", result.stdout)
            self.assertIn("ALL PASS", result.stdout)

    def test_team_league_hashes(self):
        module = kit_module()
        strategies = ["RANDOM"]*2 + ["MATCH"]*2 + ["PLUS1"]*2 + ["BIGSMALL"]*2 + ["TEAM"]*2
        results, standings = module.league_files(2026, strategies)
        self.assertEqual(hashlib.sha256(results.encode()).hexdigest()[:8], "5255a2bf")
        self.assertEqual(hashlib.sha256(standings.encode()).hexdigest()[:8], "6a4147b7")
        self.assertIn("44 P9 P10 0:0 DRAW\n", results)
        reversed_results = []
        for mid in reversed(range(45)):
            a, b = module.PAIRS[mid]
            x, y, outcome = module.play_match(2026, mid, strategies[a-1], strategies[b-1])
            reversed_results.append(f"{mid:02d} P{a} P{b} {x}:{y} {outcome}\n")
        self.assertEqual("".join(reversed(reversed_results)), results)

    def test_choose_does_not_remove_and_random_calls_once(self):
        bot = Bot("RANDOM", 2026, 0, 1)
        rng = LCG(bot.rng.x)
        for r, prize in enumerate(prize_order(2026, 0), 1):
            before = bot.hand[:]
            expected = before[rng.next() % len(before)]
            card = bot.choose(prize, r)
            self.assertEqual((card, bot.rng.x, bot.hand), (expected, rng.x, before))
            bot.play(prize, r, card, 0)
        self.assertEqual(bot.hand, [])

    def test_team_preserves_highest_and_uses_no_random(self):
        self.assertEqual(team_choose(4, 1, [2, 6, 9], [], {4, 7, 10}, None), 6)
        self.assertEqual(team_choose(7, 2, [2, 9], [], {7, 10}, None), 2)
        self.assertEqual(team_choose(10, 3, [2, 9], [], {10}, None), 9)
        bot = Bot("TEAM", 2026, 0, 9)
        state = bot.rng.x
        for r, prize in enumerate(prize_order(2026, 0), 1):
            before = bot.prizes_left.copy()
            card = bot.choose(prize, r)
            self.assertEqual(before, bot.prizes_left)
            bot.play(prize, r, card, 0)
        self.assertEqual(bot.rng.x, state)
