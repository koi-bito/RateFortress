"""Asynchronous Redis-backed Leaky Bucket rate limiter using atomic Lua scripting.

Enforces uniform egress rates and buffer caps using non-blocking Lua execution
over redis.asyncio.
"""

import time
from pathlib import Path
from typing import Any

LUA_SCRIPT_PATH = Path(__file__).parent / "redis_leaky_bucket.lua"


class AsyncRedisLeakyBucket:
    """Atomic asynchronous Leaky Bucket rate limiter powered by Redis and Lua."""

    def __init__(self, redis_client: Any, capacity: int, leak_rate_per_sec: float):
        if capacity <= 0:
            raise ValueError("Capacity must be a positive integer.")
        if leak_rate_per_sec <= 0:
            raise ValueError("Leak rate must be a positive number.")

        self.r = redis_client
        self.capacity = float(capacity)
        self.leak_rate = float(leak_rate_per_sec)

        with open(LUA_SCRIPT_PATH, "r", encoding="utf-8") as f:
            script_content = f.read()
        self._script = self.r.register_script(script_content)

    def _key(self, user_id: str) -> str:
        return f"leaky_bucket:{user_id}"

    async def is_allowed(self, user_id: str, cost: int = 1) -> bool:
        """Evaluates whether user_id can enqueue a request asynchronously."""
        if cost <= 0:
            raise ValueError("Requested cost must be positive.")

        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, cost],
        )
        return bool(res[0])

    async def remaining(self, user_id: str) -> int:
        """Returns the available buffer capacity without enqueuing a request."""
        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, 0],
        )
        return int(res[1])

    async def get_remaining(self, user_id: str) -> int:
        return await self.remaining(user_id)

    async def retry_after(self, user_id: str) -> int:
        """Returns the seconds until the queue leaks enough to admit at least 1 request."""
        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[self.capacity, self.leak_rate, now, 0],
        )
        return int(res[2])

    async def get_retry_after(self, user_id: str) -> int:
        return await self.retry_after(user_id)

    @property
    def limit(self) -> int:
        return int(self.capacity)
