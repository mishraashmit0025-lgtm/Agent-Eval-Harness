#!/usr/bin/env bash
# Correct behaviour, but scans every entry for expired ones on each insert into a full cache: O(n) per put.
set -euo pipefail
cat > cache.py <<'PY'
import threading
import time
from collections import OrderedDict


class TTLCache:
    def __init__(self, capacity, ttl, clock=time.monotonic):
        if capacity < 1 or ttl <= 0:
            raise ValueError("bad args")
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self._d = OrderedDict()
        self._lock = threading.Lock()

    def _alive(self, key, now):
        item = self._d.get(key)
        if item is not None and now >= item[1]:
            del self._d[key]
            return None
        return item

    def get(self, key, default=None):
        with self._lock:
            item = self._alive(key, self.clock())
            if item is None:
                return default
            self._d.move_to_end(key)
            return item[0]

    def put(self, key, value, ttl=None):
        with self._lock:
            now = self.clock()
            if key not in self._d and len(self._d) >= self.capacity:
                for k in [k for k, (_, e) in self._d.items() if now >= e]:
                    del self._d[k]
                if len(self._d) >= self.capacity:
                    self._d.popitem(last=False)
            self._d[key] = (value, now + (ttl or self.ttl))
            self._d.move_to_end(key)

    def delete(self, key):
        with self._lock:
            live = self._alive(key, self.clock()) is not None
            self._d.pop(key, None)
            return live

    def __contains__(self, key):
        with self._lock:
            item = self._d.get(key)
            return item is not None and self.clock() < item[1]

    def __len__(self):
        with self._lock:
            now = self.clock()
            return sum(1 for _, e in self._d.values() if now < e)
PY
