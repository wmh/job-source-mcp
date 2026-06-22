from __future__ import annotations

import asyncio
import random
import time


class AdaptiveRateLimiter:
    """Process-wide async limiter that keeps the outbound call rate LOW.

    It enforces a minimum spacing between requests (serialized via a lock so
    concurrent callers cannot burst), and — crucially — when the remote signals
    rate limiting (HTTP 429) the interval is escalated and stays escalated.
    The point is not to retry harder but to call the external API less often:
    every 429 makes us slower, and we only relax gradually after sustained
    success. This is the right response to 429 rather than silently returning
    empty results.
    """

    def __init__(
        self,
        min_interval: float,
        max_interval: float,
        jitter: float = 0.0,
    ) -> None:
        self._base_interval = min_interval
        self._interval = min_interval
        self._max_interval = max_interval
        self._jitter = jitter
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        """Block until enough time has passed since the previous request."""
        async with self._lock:
            now = time.monotonic()
            wait = self._interval + random.uniform(0, self._jitter) - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    def penalize(self) -> None:
        """Back off after a 429: double the spacing, capped at max_interval."""
        self._interval = min(self._interval * 2, self._max_interval)

    def relax(self) -> None:
        """After a success, decay slowly back toward the base spacing."""
        self._interval = max(self._base_interval, self._interval * 0.9)

    @property
    def interval(self) -> float:
        return self._interval
