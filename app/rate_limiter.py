"""Per-client token bucket rate limiter."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after: float


class TokenBucketRateLimiter:
    """Allows bursts up to `capacity`, refilling at `refill_rate` tokens/second."""

    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        clock: Callable[[], float] = time.monotonic,
        max_clients: int = 100_000,
    ) -> None:
        if capacity <= 0 or refill_rate <= 0:
            raise ValueError("capacity and refill_rate must be positive")
        self._capacity = capacity
        self._rate = refill_rate
        self._clock = clock
        self._max_clients = max_clients
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    def acquire(self, client_id: str, cost: float = 1.0) -> Decision:
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(client_id)
            if bucket is None:
                if len(self._buckets) >= self._max_clients:
                    self._evict_full_buckets(now)
                bucket = _Bucket(tokens=float(self._capacity), updated_at=now)
                self._buckets[client_id] = bucket
            else:
                elapsed = now - bucket.updated_at
                bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._rate)
                bucket.updated_at = now

            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return Decision(True, math.floor(bucket.tokens), 0.0)
            deficit = cost - bucket.tokens
            return Decision(False, 0, deficit / self._rate)

    def _evict_full_buckets(self, now: float) -> None:
        """Drop buckets that have fully refilled; they carry no state worth keeping."""
        stale = [
            cid
            for cid, b in self._buckets.items()
            if b.tokens + (now - b.updated_at) * self._rate >= self._capacity
        ]
        for cid in stale:
            del self._buckets[cid]
