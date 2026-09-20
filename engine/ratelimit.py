"""In-process token-bucket rate limiter.

Per API process: with several workers the effective ceiling is (limit x workers), which is fine for
its purpose (stopping a runaway client from monopolising the machine), not for quota accounting.
A limit of 0 disables that bucket.
"""

import os
import threading
import time


class RateLimiter:
    MAX_KEYS = 10000

    def __init__(self, per_minute):
        self.rate = per_minute / 60.0
        self.capacity = float(per_minute)
        self._buckets = {}
        self._lock = threading.Lock()

    def allow(self, key, now=None):
        """Return (allowed, retry_after_seconds)."""
        if self.capacity <= 0:
            return True, 0
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._buckets) > self.MAX_KEYS:
                self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < 60}
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return True, 0
            self._buckets[key] = (tokens, now)
            return False, max(1, int((1 - tokens) / self.rate) + 1)


def from_env():
    """Defaults: 600 reads and 300 mutations per minute per credential subject; 1200 requests per minute per client address."""
    n = lambda name, default: int(os.environ.get(name, default))
    return {
        "read": RateLimiter(n("PLANREVIEW_RATE_READ", 600)),
        "write": RateLimiter(n("PLANREVIEW_RATE_WRITE", 300)),
        "ip": RateLimiter(n("PLANREVIEW_RATE_IP", 1200)),
    }
