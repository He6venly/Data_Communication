from pathlib import Path
import tempfile
import unittest

from tools.check_canvas import check_directory
from tools.make_canvas import run


class CanvasTests(unittest.TestCase):
    def test_generation_is_valid_and_reproducible(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            first, second = root / "first", root / "second"
            hashes1 = run(2, 200, first)
            hashes2 = run(2, 200, second)
            self.assertEqual(hashes1, hashes2)
            results, errors = check_directory(first)
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 3)
            self.assertEqual(len({result["data"] for result in results}), 3)

    def test_crlf_and_non_ascii_fail(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            run(2, 200, root)
            path = root / "canvas0.txt"
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
            _, errors = check_directory(root)
            self.assertTrue(any("CRLF" in error or "12880" in error for error in errors))

            run_root = root / "fresh"
            run(2, 200, run_root)
            path = run_root / "canvas1.txt"
            data = bytearray(path.read_bytes())
            data[0] = 0xff
            path.write_bytes(data)
            _, errors = check_directory(run_root)
            self.assertTrue(any("ASCII" in error for error in errors))

    def test_low_ink_fails(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            root.mkdir(exist_ok=True)
            blank = (" " * 160 + "\n") * 80
            for index in range(3):
                (root / f"canvas{index}.txt").write_text(blank, encoding="ascii", newline="\n")
            _, errors = check_directory(root)
            self.assertTrue(any("글자 획" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

