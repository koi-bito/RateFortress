"""Asynchronous Redis-backed Token Bucket rate limiting algorithm using atomic Lua scripting.

Guarantees full atomicity across distributed application instances while executing
asynchronously on the redis.asyncio event loop.
"""

import time
from pathlib import Path
from typing import Any

LUA_SCRIPT_PATH = Path(__file__).parent / "redis_token_bucket.lua"


class AsyncRedisTokenBucket:
    """Distributed asynchronous Token Bucket rate limiter powered by Redis Lua."""

    def __init__(
        self,
        redis_client: Any,
        capacity: int,
        refill_rate_per_sec: float,
        namespace: str = "default",
    ):
        if capacity <= 0:
            raise ValueError("Capacity must be a positive integer.")
        if refill_rate_per_sec <= 0:
            raise ValueError("Refill rate must be a positive number.")

        self.r = redis_client
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate_per_sec)
        self.namespace = namespace

        with open(LUA_SCRIPT_PATH, "r", encoding="utf-8") as f:
            script_content = f.read()
        self._script = self.r.register_script(script_content)

    def _key(self, user_id: str) -> str:
        return f"token_bucket:{self.namespace}:{user_id}"

    async def is_allowed(self, user_id: str, tokens: int = 1) -> bool:
        """Evaluates whether user_id is permitted to consume `tokens` asynchronously."""
        if tokens <= 0:
            raise ValueError("Requested tokens must be positive.")

        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[self.capacity, self.refill_rate, now, tokens],
        )
        return bool(res[0])

    async def remaining(self, user_id: str) -> int:
        """Returns the available integer token count without consuming tokens."""
        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[self.capacity, self.refill_rate, now, 0],
        )
        return int(res[1])

    async def get_remaining(self, user_id: str) -> int:
        return await self.remaining(user_id)

    async def retry_after(self, user_id: str) -> int:
        """Returns the seconds to wait until at least 1 token is refilled."""
        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[self.capacity, self.refill_rate, now, 0],
        )
        return int(res[2])

    async def get_retry_after(self, user_id: str) -> int:
        return await self.retry_after(user_id)

    @property
    def limit(self) -> int:
        return int(self.capacity)
