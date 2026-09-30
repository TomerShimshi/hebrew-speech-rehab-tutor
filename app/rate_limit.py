"""Tiny in-memory sliding-window rate limiter.

Good enough while Cloud Run runs a single instance (--max-instances 1); the
count resets when the instance restarts. Replaced by real auth in sub-plan 03.
"""

import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic):
        self._limit = limit
        self._window_s = window_s
        self._clock = clock
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = self._clock()
            while self._hits and now - self._hits[0] >= self._window_s:
                self._hits.popleft()
            if len(self._hits) >= self._limit:
                return False
            self._hits.append(now)
            return True
