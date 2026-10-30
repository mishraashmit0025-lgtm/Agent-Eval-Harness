Implement `TTLCache` in `cache.py`. It is an in-memory cache with both a size limit (least recently used eviction) and per-entry expiry, and it will be shared between threads in our web workers. The stub in `cache.py` has the interface; keep the names and signatures.

Behaviour:

- `TTLCache(capacity, ttl, clock=time.monotonic)`. `capacity < 1` or `ttl <= 0` raises `ValueError`. All time comes from `clock()`, never from the real clock directly.
- An entry written at time `t` with time-to-live `x` is expired from time `t + x` onward (at exactly `t + x` it is already expired).
- `put(key, value, ttl=None)` inserts or replaces an entry. `ttl` overrides the default for that entry. Writing a key makes it the most recently used and restarts its expiry.
- `get(key, default=None)` returns the value of a live entry and makes it the most recently used. For a missing or expired key it returns `default`.
- `key in cache` is true only for a live entry and does not change recency. `len(cache)` counts live entries only.
- `delete(key)` removes the key and returns whether a live entry was removed.
- When inserting a new key into a full cache, expired entries are removed first. Only if no entry has expired is the least recently used live entry evicted.
- `get` and `put` must stay fast with large caches: no scanning of all entries per call. A cache of 10,000 entries must handle 200,000 inserts of new keys in a few seconds.
- It must be safe to call any method from many threads at once.
