#!/usr/bin/env bash
set -euo pipefail
cat > cache.py <<'PY'
"""In-memory cache with LRU eviction and per-entry expiry."""

import heapq
import threading
import time
from collections import OrderedDict


class TTLCache:
    def __init__(self, capacity, ttl, clock=time.monotonic):
        if capacity < 1 or ttl <= 0:
            raise ValueError("capacity must be >= 1 and ttl > 0")
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self._data = OrderedDict()  # key -> (value, expires_at, version), ordered by recency
        self._heap = []  # (expires_at, version, key); entries for overwritten keys are skipped lazily
        self._version = 0
        self._lock = threading.RLock()

    def _live(self, key, now):
        item = self._data.get(key)
        if item is None:
            return None
        if now >= item[1]:
            del self._data[key]
            return None
        return item

    def _purge_expired(self, now):
        while self._heap and self._heap[0][0] <= now:
            expires, version, key = heapq.heappop(self._heap)
            item = self._data.get(key)
            if item is not None and item[2] == version:
                del self._data[key]
        if len(self._heap) > 4 * len(self._data) + 64:  # rebuild when stale heap entries pile up
            self._heap = [(e, v, k) for k, (_, e, v) in self._data.items()]
            heapq.heapify(self._heap)

    def get(self, key, default=None):
        with self._lock:
            item = self._live(key, self.clock())
            if item is None:
                return default
            self._data.move_to_end(key)
            return item[0]

    def put(self, key, value, ttl=None):
        ttl = self.ttl if ttl is None else ttl
        if ttl <= 0:
            raise ValueError("ttl must be > 0")
        with self._lock:
            now = self.clock()
            if key not in self._data and len(self._data) >= self.capacity:
                self._purge_expired(now)
                if len(self._data) >= self.capacity:
                    self._data.popitem(last=False)
            self._version += 1
            expires = now + ttl
            self._data[key] = (value, expires, self._version)
            self._data.move_to_end(key)
            heapq.heappush(self._heap, (expires, self._version, key))

    def delete(self, key):
        with self._lock:
            live = self._live(key, self.clock()) is not None
            self._data.pop(key, None)
            return live

    def __contains__(self, key):
        with self._lock:
            item = self._data.get(key)
            return item is not None and self.clock() < item[1]

    def __len__(self):
        with self._lock:
            now = self.clock()
            return sum(1 for _, e, _ in self._data.values() if now < e)
PY
