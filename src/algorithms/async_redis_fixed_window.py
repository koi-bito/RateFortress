"""Asynchronous Redis-backed Fixed Window Counter rate limiting algorithm.

Performs non-blocking atomic INCR and EXPIRE operations using redis.asyncio,
ensuring the ASGI event loop remains completely unblocked during rate evaluation.
"""

import time
from typing import Any


class AsyncRedisFixedWindow:
    """Non-blocking Fixed Window Counter backed by redis.asyncio."""

    def __init__(
        self,
        redis_client: Any,
        limit: int,
        window_seconds: int,
        namespace: str = "default",
    ):
        self.r = redis_client
        self.limit = limit
        self.window_seconds = window_seconds
        self.namespace = namespace

    def _get_window_info(self, now: float | None = None):
        if now is None:
            now = time.time()
        current_window = int(now // self.window_seconds)
        seconds_into_window = now % self.window_seconds
        retry_seconds = max(1, int(self.window_seconds - seconds_into_window))
        return current_window, retry_seconds

    def _key(self, user_id: str, current_window: int) -> str:
        return f"fixed_window:{self.namespace}:{user_id}:{current_window}"

    async def is_allowed(self, user_id: str) -> bool:
        """Determines if a request from user_id is permitted in the current window."""
        now = time.time()
        current_window, _ = self._get_window_info(now)
        key = self._key(user_id, current_window)

        # Atomic async INCR
        count = await self.r.incr(key)
        if count == 1:
            await self.r.expire(key, self.window_seconds + 1)

        return count <= self.limit

    async def remaining(self, user_id: str) -> int:
        """Returns the remaining request quota for user_id in the active window."""
        current_window, _ = self._get_window_info()
        key = self._key(user_id, current_window)
        val = await self.r.get(key)
        current_count = int(val) if val is not None else 0
        return max(0, self.limit - current_count)

    async def get_remaining(self, user_id: str) -> int:
        return await self.remaining(user_id)

    async def retry_after(self, user_id: str) -> int:
        """Returns the number of seconds until the current window resets."""
        _, retry_seconds = self._get_window_info()
        return retry_seconds

    async def get_retry_after(self, user_id: str) -> int:
        return await self.retry_after(user_id)
