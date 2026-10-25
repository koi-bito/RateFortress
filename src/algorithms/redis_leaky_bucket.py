"""Redis-backed Leaky Bucket rate limiting algorithm using atomic Lua scripting.

Guarantees atomic queue management, constant leak drainage, and cross-instance synchronization.
Requests enter the bucket queue and leak out at a steady rate. If the bucket capacity is full,
new incoming requests overflow and are rejected.
"""

import time
from pathlib import Path
from typing import Any

LUA_SCRIPT_PATH = Path(__file__).parent / "redis_leaky_bucket.lua"


class RedisLeakyBucket:
    """Distributed Leaky Bucket rate limiter powered by Redis and Lua."""

    def __init__(self, redis_client: Any, capacity: int, leak_rate_per_sec: float):
        if capacity <= 0:
            raise ValueError("Capacity must be a positive integer.")
        if leak_rate_per_sec <= 0:
            raise ValueError("Leak rate must be a positive number.")

        self.r = redis_client
        self.capacity = int(capacity)
        self.leak_rate = float(leak_rate_per_sec)

        # Load Lua script and register SHA
        with open(LUA_SCRIPT_PATH, "r", encoding="utf-8") as f:
            script_content = f.read()
        self._script = self.r.register_script(script_content)

    def _key(self, user_id: str) -> str:
        return f"leaky_bucket:{user_id}"

    def is_allowed(self, user_id: str) -> bool:
        """Determines if a request by user_id fits into the bucket queue."""
        key = self._key(user_id)
        now = time.time()
        res = self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, 1],
        )
        return bool(res[0])

    def remaining(self, user_id: str) -> int:
        """Returns the number of available empty slots in the bucket queue."""
        key = self._key(user_id)
        now = time.time()
        res = self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, 0],
        )
        return int(res[1])

    def get_remaining(self, user_id: str) -> int:
        """Alias for `remaining`."""
        return self.remaining(user_id)

    def retry_after(self, user_id: str) -> int:
        """Returns the seconds to wait until at least one slot in the bucket leaks."""
        key = self._key(user_id)
        now = time.time()
        res = self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, 0],
        )
        return int(res[2])

    def get_retry_after(self, user_id: str) -> int:
        """Alias for `retry_after`."""
        return self.retry_after(user_id)

    def get_queue_size(self, user_id: str) -> int:
        """Returns the current number of requests in the bucket for user_id."""
        key = self._key(user_id)
        now = time.time()
        res = self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, 0],
        )
        return int(res[3])

    @property
    def limit(self) -> int:
        """Returns the nominal capacity of the bucket queue."""
        return self.capacity
