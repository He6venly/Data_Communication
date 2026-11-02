import hashlib
from pathlib import Path
import tempfile
import unittest

from src.assigner.partition import assignment_rows, bands, choose_worker_count, initial_halos
from src.assigner.storage import read_canvas, read_canvases


class InputTests(unittest.TestCase):
    def test_canvas_format_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canvas0.txt"
            data = (b" " * 159 + b".\n") * 80
            path.write_bytes(data)
            canvas = read_canvas(path)
            self.assertEqual(canvas.rows[0], " " * 159 + ".")
            self.assertEqual(canvas.sha256, hashlib.sha256(data).hexdigest())
            for bad in (data[:-1], data.replace(b"\n", b"\r\n"), b"\xff" + data[1:], data + b"\n"):
                path.write_bytes(bad)
                with self.assertRaises(ValueError):
                    read_canvas(path)

    def test_partition_and_wrapped_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i in range(3):
                (root / f"canvas{i}.txt").write_bytes(b"".join(
                    (f"{i}:{y:02d}".ljust(160) + "\n").encode("ascii") for y in range(80)))
            canvases = read_canvases(root)
            for n in (1, 4, 5, 6, 7, 8):
                ranges = bands(n)
                self.assertEqual(ranges[0][0], 0)
                self.assertEqual(ranges[-1][1], 80)
                for k, (y0, y1) in enumerate(ranges):
                    self.assertEqual((y0, y1), (80 * k // n, 80 * (k + 1) // n))
                    rows = assignment_rows(canvases, y0, y1)
                    h = y1 - y0
                    self.assertEqual(len(rows), 3 * h + 4)
                    self.assertEqual(rows[h], canvases[1].rows[(y0 - 1) % 80])
                    self.assertEqual(rows[-1], canvases[2].rows[y1 % 80])
                    self.assertEqual(initial_halos(canvases[0], y0, y1),
                                     (canvases[0].rows[(y0 - 1) % 80], canvases[0].rows[y1 % 80]))
            self.assertEqual(choose_worker_count(1), (1, "fixed"))
            self.assertIn(choose_worker_count()[0], range(4, 9))
            with self.assertRaises(ValueError):
                bands(3)


if __name__ == "__main__":
    unittest.main()
