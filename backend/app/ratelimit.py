"""Tiny in-process sliding-window limiter for the unauthenticated auth endpoints.

Single-replica by design (see docs/adr/0001). Account lockout, which is stored in the
database, remains the defence that survives restarts.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.errors import ApiError


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = int(self.window - (now - hits[0])) + 1
                raise ApiError(429, "rate_limited", "Too many attempts. Wait a minute and try again.",
                               headers={"Retry-After": str(retry)})
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


auth_limiter = RateLimiter(limit=20, window_seconds=60)
