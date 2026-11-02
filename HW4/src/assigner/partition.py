"""작업자별 행 범위와 초기 전달 데이터를 만든다."""

import random

from .storage import Canvas, HEIGHT


def choose_worker_count(fixed: int | None = None) -> tuple[int, str]:
    if fixed is None:
        return random.randint(4, 8), "random"
    if fixed not in (1, 4, 5, 6, 7, 8):
        raise ValueError("작업자 수는 1 또는 4~8이어야 합니다")
    return fixed, "fixed"


def bands(n: int) -> tuple[tuple[int, int], ...]:
    if n not in (1, 4, 5, 6, 7, 8):
        raise ValueError("작업자 수는 1 또는 4~8이어야 합니다")
    return tuple((HEIGHT * k // n, HEIGHT * (k + 1) // n) for k in range(n))


def assignment_rows(canvases: tuple[Canvas, Canvas, Canvas], y0: int, y1: int) -> tuple[str, ...]:
    if not 0 <= y0 < y1 <= HEIGHT:
        raise ValueError("잘못된 행 범위입니다")
    # 첫 그림은 담당 띠만, 나머지는 위아래 이웃 행까지 전달한다.
    return (canvases[0].rows[y0:y1]
            + tuple(canvases[1].rows[y % HEIGHT] for y in range(y0 - 1, y1 + 1))
            + tuple(canvases[2].rows[y % HEIGHT] for y in range(y0 - 1, y1 + 1)))


def initial_halos(canvas: Canvas, y0: int, y1: int) -> tuple[str, str]:
    if not 0 <= y0 < y1 <= HEIGHT:
        raise ValueError("잘못된 행 범위입니다")
    return canvas.rows[(y0 - 1) % HEIGHT], canvas.rows[y1 % HEIGHT]
