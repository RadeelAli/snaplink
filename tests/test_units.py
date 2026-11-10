from __future__ import annotations

import threading

import pytest

from app import codec
from app.cache import LRUCache
from app.rate_limiter import TokenBucketRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


# ---------- codec ----------


@pytest.mark.parametrize("n", [0, 1, 61, 62, 3843, 10**12])
def test_encode_decode_roundtrip(n: int) -> None:
    assert codec.decode(codec.encode(n)) == n


def test_obfuscation_is_bijective_and_non_sequential() -> None:
    codes = [codec.id_to_code(i) for i in range(1, 2001)]
    assert len(set(codes)) == len(codes)
    for i in (1, 42, 999_999):
        assert codec.deobfuscate(codec.obfuscate(i)) == i
    assert codes[0][:-1] != codes[1][:-1]  # neighbouring ids don't share a prefix


def test_decode_rejects_invalid_chars() -> None:
    with pytest.raises(ValueError):
        codec.decode("ab-c")


# ---------- cache ----------


def test_cache_evicts_least_recently_used() -> None:
    cache: LRUCache[str, int] = LRUCache(capacity=2, ttl_seconds=100)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")  # 'a' is now most recent
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1 and cache.get("c") == 3


def test_cache_entries_expire() -> None:
    clock = FakeClock()
    cache: LRUCache[str, int] = LRUCache(capacity=10, ttl_seconds=5, clock=clock)
    cache.put("k", 1)
    clock.t = 4.9
    assert cache.get("k") == 1
    clock.t = 5.0
    assert cache.get("k") is None
    assert len(cache) == 0


# ---------- rate limiter ----------


def test_rate_limiter_allows_burst_then_blocks() -> None:
    clock = FakeClock()
    rl = TokenBucketRateLimiter(capacity=3, refill_rate=1.0, clock=clock)
    assert all(rl.acquire("ip").allowed for _ in range(3))
    decision = rl.acquire("ip")
    assert not decision.allowed
    assert decision.retry_after == pytest.approx(1.0)


def test_rate_limiter_refills_over_time_and_isolates_clients() -> None:
    clock = FakeClock()
    rl = TokenBucketRateLimiter(capacity=1, refill_rate=2.0, clock=clock)
    assert rl.acquire("a").allowed
    assert not rl.acquire("a").allowed
    assert rl.acquire("b").allowed  # other clients unaffected
    clock.t = 0.5
    assert rl.acquire("a").allowed


def test_rate_limiter_is_thread_safe() -> None:
    rl = TokenBucketRateLimiter(capacity=100, refill_rate=1e-9)
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(50):
            ok = rl.acquire("shared").allowed
            with lock:
                results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 100  # exactly capacity, never more
