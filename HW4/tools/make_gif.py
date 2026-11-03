"""한 원격 실행의 frame 301장으로 진행 GIF를 만든다."""

import argparse
from pathlib import Path
import sys
import tempfile

from .formats import FRAME_ROUNDS, read_grid
from .verify_run import verify_run_directory


FONT_PATHS = (
    "DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)
COLORS = ((127, 224, 255), (255, 150, 125), (205, 180, 255))


# 운영체제별 후보에서 사용할 수 있는 고정폭 글꼴을 찾는다.
def load_font(ImageFont, size):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise OSError("사용할 수 있는 고정폭 글꼴을 찾지 못했습니다")


# 저장된 문자 frame을 Worker 경계와 상태 번호가 보이는 그림으로 바꾼다.
def render_frames(run_dir, n):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("GIF 제작에는 Pillow가 필요합니다") from exc

    font = load_font(ImageFont, 10)
    char_width, char_height = 6, 10
    left, top = 34, 24
    width, height = 1000, 830
    bounds = [80 * k // n for k in range(n + 1)]
    images = []
    durations = []
    for r in FRAME_ROUNDS:
        _, rows = read_grid(Path(run_dir) / "frames" / f"frame{r:04d}.txt")
        rule = min(r // 1000, 2)
        image = Image.new("RGB", (width, height), (12, 20, 32))
        draw = ImageDraw.Draw(image)
        draw.text((6, 6), f"Round {r:4d} / 3000   Rule{rule + 1}   N={n}",
                  font=font, fill=COLORS[rule])
        for k in range(n):
            y = top + bounds[k] * char_height
            draw.line(((left, y), (left + 160 * char_width, y)), fill=(60, 75, 100))
            draw.text((4, y + 2), f"W{k}", font=font, fill=(150, 160, 180))
        for y, row in enumerate(rows):
            draw.text((left, top + y * char_height), row, font=font, fill=COLORS[rule])
        images.append(image.convert("P", palette=Image.Palette.ADAPTIVE, colors=32))
        durations.append(1000 if r in (0, 1000, 2000, 3000) else 80)
    return images, durations


# 저장된 GIF의 프레임 수와 처음·마지막 상태를 다시 디코딩해 검사한다.
def validate_saved_gif(path, expected_first, expected_last):
    from PIL import Image, ImageChops

    with Image.open(path) as gif:
        if gif.size != (1000, 830):
            raise ValueError("생성된 GIF 크기가 잘못됐습니다")
        if getattr(gif, "n_frames", 1) != 301:
            raise ValueError("생성된 GIF는 실제 301프레임이어야 합니다")

        decoded_first = None
        decoded_last = None
        for index in range(301):
            gif.seek(index)
            gif.load()
            if index == 0:
                decoded_first = gif.convert("RGB")
            elif index == 300:
                decoded_last = gif.convert("RGB")

        if ImageChops.difference(decoded_first,
                                 expected_first.convert("RGB")).getbbox() is not None:
            raise ValueError("GIF의 처음 그림이 canvas0 상태와 다릅니다")
        if ImageChops.difference(decoded_last,
                                 expected_last.convert("RGB")).getbbox() is not None:
            raise ValueError("GIF의 마지막 그림이 round3000 상태와 다릅니다")


# 유효한 실행의 frame 301장으로 GIF를 만들고 저장 결과를 검증한다.
def make_gif(run_dir, output):
    info, errors, _ = verify_run_directory(run_dir)
    if errors:
        return errors
    output = Path(output)
    if output.exists():
        return [f"{output}: 기존 파일을 덮어쓸 수 없습니다"]
    output.parent.mkdir(parents=True, exist_ok=True)
    images, durations = render_frames(run_dir, info["n"])
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".gif", dir=output.parent,
                                         delete=False) as temp:
            temp_path = Path(temp.name)
        images[0].save(temp_path, save_all=True, append_images=images[1:],
                       duration=durations, loop=0, optimize=False, disposal=2)
        validate_saved_gif(temp_path, images[0], images[-1])
        temp_path.replace(output)
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    finally:
        for image in images:
            image.close()
    return []


# GIF 생성에 필요한 실행 폴더와 출력 파일 인자를 정의한다.
def parser():
    result = argparse.ArgumentParser(description="HW4 진행 GIF 생성")
    result.add_argument("--run-dir", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    return result


# GIF 생성 결과의 프레임 수와 파일 크기를 출력한다.
def main(argv=None):
    args = parser().parse_args(argv)
    try:
        errors = make_gif(args.run_dir, args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"GIF 생성 실패: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    size_mb = args.output.stat().st_size / 1_000_000
    print(f"{args.output}: 301 frames, {size_mb:.1f} MB")
    if size_mb > 30:
        print("WARN: 권장 크기 30MB를 넘었습니다", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

