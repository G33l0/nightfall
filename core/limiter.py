"""Global asynchronous request-rate limiter (token bucket).

A single limiter instance is shared by every worker so the *aggregate*
request rate can be capped, regardless of how many concurrent users are
active. This is the mechanism that lets a tester control how much traffic
NIGHTFALL generates (spec sections 5 and 29).
"""
from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token-bucket limiter allowing up to ``rate`` acquisitions per second.

    ``rate <= 0`` disables limiting entirely (acquire returns immediately).
    The bucket can hold at most ``rate`` tokens so bursts never exceed one
    second of budget.
    """

    def __init__(self, rate: float) -> None:
        self._rate = float(rate)
        # Cap the burst budget to at most one second of rate, and start the
        # bucket EMPTY so the very first second cannot exceed the configured
        # rate (avoids a large initial spike at test start).
        self._capacity = float(rate) if rate > 0 else 0.0
        self._tokens = 0.0
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def rate(self) -> float:
        return self._rate

    async def acquire(self) -> None:
        """Block until a single request token is available."""
        if self._rate <= 0:
            return
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._updated
                self._updated = now
                self._tokens = min(
                    self._capacity, self._tokens + elapsed * self._rate
                )
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # How long until the next token becomes available?
                deficit = 1.0 - self._tokens
                wait = deficit / self._rate
            await asyncio.sleep(wait)
