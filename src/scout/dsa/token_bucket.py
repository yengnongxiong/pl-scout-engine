"""Token-bucket rate limiter for polite ingestion (PRD §14, CLAUDE.md rule 11).

A bucket holds up to ``capacity`` tokens and refills continuously at ``rate`` tokens per
second. Each request spends one token; when the bucket is empty the caller waits exactly
long enough for the next token. Unlike a fixed "sleep N seconds" this allows a small burst
(``capacity``) while enforcing the long-run average ``rate``.

Complexity: ``acquire`` / ``try_acquire`` are O(1) time; the bucket uses O(1) space.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class TokenBucket:
    """Continuous-refill token bucket.

    Args:
        rate: Refill rate in tokens per second (> 0).
        capacity: Maximum burst size in tokens (>= 1).
        clock: Monotonic clock in seconds; injectable for tests.
        sleep: Sleep function; injectable for tests.
    """

    def __init__(
        self,
        rate: float,
        capacity: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.rate = rate
        self.capacity = capacity
        self._clock = clock
        self._sleep = sleep
        self._tokens = capacity
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last = now

    @property
    def tokens(self) -> float:
        """Tokens currently available (after refill)."""
        self._refill()
        return self._tokens

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Spend ``tokens`` if available without waiting. O(1)."""
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def acquire(self, tokens: float = 1.0) -> float:
        """Spend ``tokens``, sleeping until they are available. O(1).

        Returns:
            The number of seconds slept.
        """
        if tokens > self.capacity:
            raise ValueError("cannot acquire more tokens than the bucket capacity")
        self._refill()
        waited = 0.0
        if self._tokens < tokens:
            wait = (tokens - self._tokens) / self.rate
            self._sleep(wait)
            waited = wait
            self._refill()
            # Guard against clocks that advance slightly less than requested.
            self._tokens = max(self._tokens, tokens)
        self._tokens -= tokens
        return waited
