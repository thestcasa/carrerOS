from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Lock

from app.auth.contracts import RateLimitDecision


class FixedWindowRateLimiter:
    def __init__(
        self,
        *,
        limit: int,
        window: timedelta,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if limit < 1 or window <= timedelta(0):
            raise ValueError("rate limit and window must be positive")
        self._limit = limit
        self._seconds = int(window.total_seconds())
        if self._seconds < 1:
            raise ValueError("window must be at least one second")
        self._now = now or (lambda: datetime.now(UTC))
        self._counts: dict[tuple[str, int], int] = {}
        self._lock = Lock()

    def check(self, key: str) -> RateLimitDecision:
        if not key:
            raise ValueError("rate-limit key cannot be empty")
        now = self._now().astimezone(UTC)
        timestamp = int(now.timestamp())
        window_start = timestamp - timestamp % self._seconds
        bucket = (key, window_start)
        with self._lock:
            count = self._counts.get(bucket, 0)
            allowed = count < self._limit
            if allowed:
                count += 1
                self._counts[bucket] = count
        return RateLimitDecision(
            allowed=allowed,
            limit=self._limit,
            remaining=max(0, self._limit - count),
            reset_at=datetime.fromtimestamp(window_start + self._seconds, UTC),
        )
