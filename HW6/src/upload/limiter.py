"""Peer 전체 업로드가 하나의 평균 속도 한도를 나눠 쓰게 한다."""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, bytes_per_sec: int) -> None:
        """Peer 전체에서 공유할 초당 바이트 한도와 다음 예약 시각을 준비한다."""
        self.rate = max(0, int(bytes_per_sec))
        self._lock = threading.Lock()
        self._next_at = 0.0

    def take(self, size: int) -> None:
        """lock 안에서는 전송 차례만 예약하고 실제 대기는 lock 밖에서 한다."""
        if size <= 0 or self.rate <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_at)
            self._next_at = start + size / self.rate
        delay = start - now
        if delay > 0:
            time.sleep(delay)
