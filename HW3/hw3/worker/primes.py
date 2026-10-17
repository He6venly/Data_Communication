# 구간 체로 Task·step 범위의 소수 개수를 계산한다.

from math import isqrt


def _build_small_primes() -> tuple[int, ...]:
    flags = [True] * 10_001
    flags[0] = flags[1] = False
    for p in range(2, isqrt(10_000) + 1):
        if flags[p]:
            for multiple in range(p * p, 10_001, p):
                flags[multiple] = False
    return tuple(i for i, prime in enumerate(flags) if prime)


_SMALL_PRIMES = _build_small_primes()


def small_primes() -> tuple[int, ...]:
    return _SMALL_PRIMES


def step_bounds(task: int, step: int) -> tuple[int, int]:
    if not 0 <= task < 1_000 or not 1 <= step <= 10:
        raise ValueError("task must be 0..999 and step must be 1..10")
    lo = task * 100_000 + (step - 1) * 10_000 + 1
    return lo, lo + 9_999


def count_step(task: int, step: int) -> int:
    lo, hi = step_bounds(task, step)
    flags = [True] * (hi - lo + 1)
    if lo == 1:
        flags[0] = False
    for p in small_primes():
        if p * p > hi:
            break
        start = max(p * p, ((lo + p - 1) // p) * p)
        for multiple in range(start, hi + 1, p):
            flags[multiple - lo] = False
    return sum(flags)
