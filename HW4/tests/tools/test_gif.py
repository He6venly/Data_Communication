from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from tools.make_gif import make_gif, validate_saved_gif
from fixture import make_run


class GifTests(unittest.TestCase):
    def test_gif_does_not_replace_file_created_during_generation(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / "result.gif"
            original = b"another process's output"
            image = Image.new("P", (1, 1))
            with (patch("tools.make_gif.verify_run_directory", return_value=({"n": 4}, [], {})),
                  patch("tools.make_gif.render_frames", return_value=([image], [80])),
                  patch("tools.make_gif.validate_saved_gif",
                        side_effect=lambda *_: output.write_bytes(original))):
                with self.assertRaises(FileExistsError):
                    make_gif(Path(name), output)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(list(output.parent.iterdir()), [output])

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

