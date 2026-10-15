"""Inclusive segmented sieve for the fixed HW3 task/step ranges."""

from functools import lru_cache
from math import isqrt


@lru_cache(maxsize=1)
def small_primes() -> tuple[int, ...]:
    """Primes through sqrt(100,000,000), shared read-only within this process."""
    flags = bytearray(b"\x01") * 10_001
    flags[:2] = b"\x00\x00"
    for p in range(2, isqrt(10_000) + 1):
        if flags[p]:
            start = p * p
            flags[start::p] = b"\x00" * ((10_000 - start) // p + 1)
    return tuple(i for i, prime in enumerate(flags) if prime)


def step_bounds(task: int, step: int) -> tuple[int, int]:
    if not 0 <= task < 1_000 or not 1 <= step <= 10:
        raise ValueError("task must be 0..999 and step must be 1..10")
    lo = task * 100_000 + (step - 1) * 10_000 + 1
    return lo, lo + 9_999


def count_step(task: int, step: int) -> int:
    lo, hi = step_bounds(task, step)
    flags = bytearray(b"\x01") * (hi - lo + 1)
    if lo == 1:
        flags[0] = 0
    for p in small_primes():
        if p * p > hi:
            break
        start = max(p * p, ((lo + p - 1) // p) * p)
        if start <= hi:
            flags[start - lo::p] = b"\x00" * ((hi - start) // p + 1)
    return sum(flags)
