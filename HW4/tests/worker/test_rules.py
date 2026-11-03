import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from src.worker.board import Board
from src.worker import rules
from src.worker.reference import read_canvas, run


def pack():
    value = os.environ.get("HW4_PACK_DIR")
    if not value:
        raise AssertionError("HW4_PACK_DIR에 원본 배포팩 경로가 필요합니다")
    root = Path(value)
    if not all((root / name).is_dir() for name in ("1_rule_test_kit", "2_tools", "3_G11_sample")):
        raise AssertionError("배포팩 필수 폴더가 없습니다")
    return root


def read(path):
    return [list(row) for row in path.read_bytes().decode("ascii").splitlines()]


def encoded(rows):
    return ("\n".join("".join(row) for row in rows) + "\n").encode("ascii")


def whole(rows, cell):
    work = [rows[-1]] + rows + [rows[0]]
    return [[cell(work, i, x) for x in range(len(rows[0]))] for i in range(1, len(rows)+1)]


class OfficialRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kit = pack() / "1_rule_test_kit"

    def test_repaint_brian_and_first_round(self):
        work = read(self.kit / "repaint_S1000.txt")
        rules.repaint(work, read(self.kit / "repaint_canvas1.txt"))
        self.assertEqual(encoded(work), (self.kit / "repaint_step1_painted.txt").read_bytes())
        rules.to_brian(work)
        self.assertEqual(encoded(work), (self.kit / "repaint_step2_brian.txt").read_bytes())
        self.assertEqual(encoded(whole(work, rules.rule2_cell)),
                         (self.kit / "repaint_step3_R1000.txt").read_bytes())

    def test_cyclic_global_y(self):
        work = read(self.kit / "cyclic_convert_input.txt")
        rules.to_cyclic(work, 25, 11)
        self.assertEqual(encoded(work), (self.kit / "cyclic_convert_output_y25_team11.txt").read_bytes())

    def test_three_bands(self):
        combined = []
        for k in range(3):
            work = read(self.kit / f"band_N3_W{k}_work.txt")
            result = [[rules.rule1_cell(work, i, x) for x in range(len(work[0]))]
                      for i in range(1, len(work)-1)]
            self.assertEqual(encoded(result), (self.kit / f"band_N3_W{k}_output.txt").read_bytes())
            combined.extend(result)
        self.assertEqual(encoded(combined), (self.kit / "rule1_output_R1.txt").read_bytes())

    def test_original_runner_with_temporary_adapter(self):
        with tempfile.TemporaryDirectory(prefix="hw4 official kit ") as directory:
            target = Path(directory)
            shutil.copytree(self.kit, target, dirs_exist_ok=True)
            adapter = (self.kit / "python" / "myrules.py").read_text(encoding="utf-8")
            adapter += ("\nfrom src.worker.rules import (rule1_cell, rule2_cell, rule3_cell, "
                        "repaint, to_brian, to_cyclic)\n")
            (target / "python" / "myrules.py").write_text(adapter, encoding="utf-8")
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                   "PYTHONIOENCODING": "utf-8"}
            result = subprocess.run([sys.executable, str(target / "python" / "rule_test.py")],
                                    cwd=target, env=env, capture_output=True, text=True, encoding="utf-8", timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count("[PASS]"), 10)
            self.assertIn("ALL PASS", result.stdout)
            self.assertNotIn("[FAIL]", result.stdout)


def official_case(rule, rounds):
    # 원본 입력을 직접 계산하고 키트 정답이랑 바이트까지 같은지 확인함
    def test(self):
        rows = read(self.kit / f"rule{rule}_input.txt")
        for _ in range(rounds):
            rows = whole(rows, getattr(rules, f"rule{rule}_cell"))
        self.assertEqual(encoded(rows), (self.kit / f"rule{rule}_output_R{rounds}.txt").read_bytes())
    return test


for rule, rounds in ((1, (1, 2, 3, 10)), (2, (1, 2, 3)), (3, (1, 2, 10))):
    for count in rounds:
        setattr(OfficialRules, f"test_rule{rule}_R{count}", official_case(rule, count))


class BoardTests(unittest.TestCase):
    def test_double_buffer_and_order(self):
        initial = ["     ", " ABC ", "     "]
        paint = ["     "] * 5
        board = Board(initial, paint, paint, 0, 2)
        expected = whole([list(row) for row in initial], rules.rule1_cell)
        board.step(0, initial[-1], initial[0])
        self.assertEqual(encoded(board.rows()), encoded(expected))
        self.assertEqual(initial, ["     ", " ABC ", "     "])
        with self.assertRaises(ValueError):
            board.step(0, initial[-1], initial[0])

    def test_transition_halos_and_wrapped_global_y(self):
        # 띠 경계랑 위아래로 이어지는 Halo도 전체 판을 계산한 결과랑 같은지 확인함
        for r in (1000, 2000):
            full = [[" "] * 160 for _ in range(80)]
            paint = [[" "] * 160 for _ in range(80)]
            paint[79][0:3] = "ABC"
            paint[0][159] = "X"
            paint[13][2] = "#"
            expected_work = [full[-1][:]] + [row[:] for row in full] + [full[0][:]]
            ext = [paint[-1][:]] + [row[:] for row in paint] + [paint[0][:]]
            rules.repaint(expected_work, ext)
            if r == 1000:
                rules.to_brian(expected_work)
                cell = rules.rule2_cell
            else:
                rules.to_cyclic(expected_work, 79, 11)
                cell = rules.rule3_cell
            expected = [[cell(expected_work, i, x) for x in range(160)] for i in range(1, 81)]
            for n in (1, 6, 7):
                combined = []
                for k in range(n):
                    y0, y1 = 80*k//n, 80*(k+1)//n
                    fragment = [paint[y % 80] for y in range(y0-1, y1+1)]
                    board = Board(full[y0:y1], fragment, fragment, y0, 11)
                    board.round = r
                    board.step(r, full[(y0-1) % 80], full[y1 % 80])
                    combined.extend(board.rows())
                self.assertEqual(encoded(combined), encoded(expected))

    def test_result_snapshot_cadence(self):
        board = Board([" "*160]*13, [" "*160]*15, [" "*160]*15, 0, 2)
        for r in (0, 8, 9, 999, 1000, 1999, 2000, 2999):
            lines = board.result(r, 0).splitlines()
            self.assertEqual(len(lines), 16 if (r+1) % 10 == 0 else 3)
            self.assertEqual(lines[0], f"RESULT {r} 0".encode())
            self.assertTrue(all(len(line) == 160 for line in lines[1:]))


class ReferenceTests(unittest.TestCase):
    def test_g11_all_31_hashes_and_bytes(self):
        sample = pack() / "3_G11_sample"
        with tempfile.TemporaryDirectory(prefix="hw4 reference ") as temp:
            out = Path(temp) / "output"
            hashes = run(11, sample, out)
            expected = [line for line in (sample / "RoundHash_N1.txt").read_text().splitlines()
                        if line.startswith("round")]
            self.assertEqual(hashes, expected)
            self.assertEqual(len(hashes), 31)
            for entry in hashes:
                name = entry.split()[0]
                self.assertEqual((out / name).read_bytes(), (sample / "rounds_N6" / name).read_bytes())
            self.assertEqual(len(list(out.iterdir())), 32)
            with self.assertRaises(ValueError):
                run(11, sample, out)

    def test_reject_bad_canvas(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "canvas.txt"
            valid = (b" "*160 + b"\n")*80
            for data in (valid[:-1], valid.replace(b"\n", b"\r\n"),
                         b"\xef\xbb\xbf"+valid, b"\t"+valid[1:], b"\x7f"+valid[1:]):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    read_canvas(path)
