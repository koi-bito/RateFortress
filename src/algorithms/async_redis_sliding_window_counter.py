"""Asynchronous Redis-backed Sliding Window Counter rate limiting algorithm using atomic Lua scripting.

Smooths window boundaries using a weighted rolling estimate with O(1) memory,
executing non-blocking atomic Lua script calls via redis.asyncio.
"""

import time
from pathlib import Path
from typing import Any

LUA_SCRIPT_PATH = Path(__file__).parent / "redis_sliding_window_counter.lua"


class AsyncRedisSlidingWindowCounter:
    """Non-blocking atomic Sliding Window Counter backed by redis.asyncio and Lua."""

    def __init__(
        self,
        redis_client: Any,
        limit: int,
        window_seconds: int,
        namespace: str = "default",
    ):
        if limit <= 0:
            raise ValueError("Limit must be positive.")
        if window_seconds <= 0:
            raise ValueError("Window seconds must be positive.")

        self.r = redis_client
        self.limit = limit
        self.window_seconds = window_seconds
        self.namespace = namespace

        with open(LUA_SCRIPT_PATH, "r", encoding="utf-8") as f:
            script_content = f.read()
        self._script = self.r.register_script(script_content)

    def _get_window_info(self, now: float | None = None):
        if now is None:
            now = time.time()
        current_window = int(now // self.window_seconds)
        previous_window = current_window - 1
        elapsed_in_window = now - (current_window * self.window_seconds)
        weight_prev = max(0.0, 1.0 - (elapsed_in_window / self.window_seconds))
        return current_window, previous_window, weight_prev

    def _keys(self, user_id: str, now: float | None = None):
        curr_win, prev_win, weight_prev = self._get_window_info(now)
        # Unified key prefix with sync Redis: swc:{namespace}:{user_id}:{window}
        curr_key = f"swc:{self.namespace}:{user_id}:{curr_win}"
        prev_key = f"swc:{self.namespace}:{user_id}:{prev_win}"
        return curr_key, prev_key, weight_prev

    async def is_allowed(self, user_id: str) -> bool:
        """Determines if a request from user_id is permitted based on the atomic weighted count."""
        now = time.time()
        curr_key, prev_key, weight_prev = self._keys(user_id, now)
        ttl = 2 * self.window_seconds + 2

        res = await self._script(
            keys=[curr_key, prev_key],
            args=[self.limit, self.window_seconds, weight_prev, ttl, 1],
        )
        return bool(res[0])

    async def remaining(self, user_id: str) -> int:
        """Returns the estimated remaining request quota for user_id."""
        now = time.time()
        curr_key, prev_key, weight_prev = self._keys(user_id, now)
        ttl = 2 * self.window_seconds + 2

        res = await self._script(
            keys=[curr_key, prev_key],
            args=[self.limit, self.window_seconds, weight_prev, ttl, 0],
        )
        return int(res[1])

    async def get_remaining(self, user_id: str) -> int:
        return await self.remaining(user_id)

    async def retry_after(self, user_id: str) -> int:
        """Returns the seconds remaining until the rate limit permits a request."""
        now = time.time()
        curr_key, prev_key, weight_prev = self._keys(user_id, now)
        ttl = 2 * self.window_seconds + 2

        res = await self._script(
            keys=[curr_key, prev_key],
            args=[self.limit, self.window_seconds, weight_prev, ttl, 0],
        )
        return int(res[2])

    async def get_retry_after(self, user_id: str) -> int:
        return await self.retry_after(user_id)
