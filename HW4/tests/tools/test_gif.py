from pathlib import Path
import tempfile
import unittest

from PIL import Image

from tools.make_gif import make_gif, validate_saved_gif
from fixture import make_run


class GifTests(unittest.TestCase):
    def test_gif_has_all_frames(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            run = make_run(root / "run", 4, "random")
            output = root / "result.gif"
            errors = make_gif(run, output)
            self.assertEqual(errors, [])
            with Image.open(output) as image:
                self.assertEqual(image.size, (1000, 830))
                self.assertEqual(image.n_frames, 301)
                image.seek(0)
                first = image.convert("RGB")
                image.seek(300)
                last = image.convert("RGB")

            wrong_first = first.copy()
            wrong_first.putpixel((999, 829), (255, 255, 255))
            with self.assertRaisesRegex(ValueError, "처음 그림"):
                validate_saved_gif(output, wrong_first, last)

            wrong_last = last.copy()
            wrong_last.putpixel((999, 829), (255, 255, 255))
            with self.assertRaisesRegex(ValueError, "마지막 그림"):
                validate_saved_gif(output, first, wrong_last)


if __name__ == "__main__":
    unittest.main()

