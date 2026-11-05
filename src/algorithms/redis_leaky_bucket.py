"""Redis-backed Leaky Bucket rate limiting algorithm using atomic Lua scripting."""

import time
from pathlib import Path
from typing import Any

LUA_SCRIPT_PATH = Path(__file__).parent / "redis_leaky_bucket.lua"


class RedisLeakyBucket:
    """Distributed Leaky Bucket rate limiter powered by Redis and Lua."""

    def __init__(
        self,
        redis_client: Any,
        capacity: int,
        leak_rate_per_sec: float,
        namespace: str = "default",
    ):
        if capacity <= 0:
            raise ValueError("Capacity must be a positive integer.")
        if leak_rate_per_sec <= 0:
            raise ValueError("Leak rate must be a positive number.")

        self.r = redis_client
        self.capacity = int(capacity)
        self.leak_rate = float(leak_rate_per_sec)
        self.namespace = namespace

        # Load Lua script and register SHA
        with open(LUA_SCRIPT_PATH, "r", encoding="utf-8") as f:
            script_content = f.read()
        self._script = self.r.register_script(script_content)

    def _key(self, user_id: str) -> str:
        return f"leaky_bucket:{self.namespace}:{user_id}"

    def is_allowed(self, user_id: str) -> bool:
        key = self._key(user_id)
        now = time.time()
        res = self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, 1],
        )
        return bool(res[0])

    def remaining(self, user_id: str) -> int:
        key = self._key(user_id)
        now = time.time()
        res = self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, 0],
        )
        return int(res[1])

    def get_remaining(self, user_id: str) -> int:
        return self.remaining(user_id)

    def retry_after(self, user_id: str) -> int:
        key = self._key(user_id)
        now = time.time()
        res = self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, 0],
        )
        return int(res[2])

    def get_retry_after(self, user_id: str) -> int:
        return self.retry_after(user_id)

    def get_queue_size(self, user_id: str) -> int:
        key = self._key(user_id)
        now = time.time()
        res = self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, 0],
        )
        return int(res[3])

    @property
    def limit(self) -> int:
        return self.capacity
