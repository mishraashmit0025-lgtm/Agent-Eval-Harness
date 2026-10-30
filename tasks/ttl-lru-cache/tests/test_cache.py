import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.environ["WORKSPACE"])
from cache import TTLCache  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


@pytest.fixture
def clock():
    return Clock()


def test_validation():
    for args in [(0, 1), (-1, 1), (1, 0), (1, -2)]:
        with pytest.raises(ValueError):
            TTLCache(*args)


def test_basic_get_put(clock):
    c = TTLCache(3, 10, clock)
    c.put("a", 1)
    assert c.get("a") == 1 and c.get("zz") is None and c.get("zz", 5) == 5
    c.put("a", 2)
    assert c.get("a") == 2 and len(c) == 1


def test_expiry_boundary_is_exclusive(clock):
    c = TTLCache(3, 8, clock)
    c.put("a", 1)
    clock.advance(7.5)
    assert c.get("a") == 1
    clock.advance(0.5)
    assert c.get("a") is None and "a" not in c and len(c) == 0


def test_per_entry_ttl_and_rewrite_restarts_expiry(clock):
    c = TTLCache(3, 10, clock)
    c.put("short", 1, ttl=2)
    c.put("long", 2)
    clock.advance(5)
    c.put("long", 3)  # now expires at +15
    clock.advance(7)
    assert c.get("short") is None and c.get("long") == 3


def test_lru_eviction_order(clock):
    c = TTLCache(3, 100, clock)
    for k in "abc":
        c.put(k, k)
    assert c.get("a") == "a"  # a becomes most recent, so b is least recent
    c.put("d", "d")
    assert "b" not in c and all(k in c for k in "acd")


def test_contains_does_not_touch_recency(clock):
    c = TTLCache(2, 100, clock)
    c.put("a", 1)
    c.put("b", 2)
    assert "a" in c  # must not refresh a
    c.put("c", 3)
    assert "a" not in c and "b" in c and "c" in c


def test_expired_entries_are_evicted_before_live_ones(clock):
    c = TTLCache(3, 100, clock)
    c.put("old", 1)  # least recently used, but still live
    c.put("temp", 2, ttl=1)
    c.put("mid", 3)
    clock.advance(2)
    c.put("new", 4)
    assert "old" in c and "mid" in c and "new" in c and "temp" not in c


def test_update_of_existing_key_never_evicts(clock):
    c = TTLCache(2, 100, clock)
    c.put("a", 1)
    c.put("b", 2)
    c.put("a", 3)
    assert c.get("a") == 3 and c.get("b") == 2


def test_delete(clock):
    c = TTLCache(3, 10, clock)
    c.put("a", 1)
    assert c.delete("a") is True and c.delete("a") is False
    c.put("b", 1)
    clock.advance(11)
    assert c.delete("b") is False


def test_len_counts_only_live(clock):
    c = TTLCache(10, 10, clock)
    for i in range(5):
        c.put(i, i, ttl=i + 1)
    clock.advance(3)
    assert len(c) == 2


def test_uses_injected_clock_only():
    t = [0.0]
    c = TTLCache(5, 60, lambda: t[0])
    c.put("a", 1)
    time.sleep(0.05)
    assert c.get("a") == 1
    t[0] = 61
    assert c.get("a") is None


def test_large_cache_is_fast(clock):
    c = TTLCache(10_000, 1e9, clock)
    start = time.perf_counter()
    for i in range(200_000):
        c.put(i, i)
        clock.advance(0.0001)
        if i % 1000 == 0:
            assert time.perf_counter() - start < 6, f"too slow: only {i} inserts in 6s"
    for i in range(190_000, 200_000):
        assert c.get(i) == i
    assert c.get(0) is None
    assert time.perf_counter() - start < 6, "put/get scale with the number of entries"


def test_large_cache_with_expiries_is_fast(clock):
    c = TTLCache(5_000, 1.0, clock)
    start = time.perf_counter()
    for i in range(100_000):
        c.put(i, i, ttl=0.5 if i % 2 else 50)
        clock.advance(0.001)
        if i % 1000 == 0:
            assert time.perf_counter() - start < 6, f"too slow: only {i} inserts in 6s"
    assert time.perf_counter() - start < 6
    assert len(c) <= 5_000


def test_thread_safety():
    c = TTLCache(500, 1e9)
    errors = []

    def worker(n):
        try:
            for i in range(5_000):
                k = (n * 7 + i) % 800
                c.put(k, (n, i))
                v = c.get(k)
                assert v is None or isinstance(v, tuple)
                if i % 50 == 0:
                    c.delete(k)
                    len(c)
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:3]
    assert len(c) <= 500
