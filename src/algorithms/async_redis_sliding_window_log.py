"""Asynchronous Redis-backed Sliding Window Log rate limiter using atomic Lua scripting.

Maintains precise millisecond-level window logs using Redis Sorted Sets (ZSET)
via non-blocking redis.asyncio Lua calls.
"""

import time
import uuid
from pathlib import Path
from typing import Any

LUA_SCRIPT_PATH = Path(__file__).parent / "redis_sliding_window_log.lua"


class AsyncRedisSlidingWindowLog:
    """Atomic asynchronous Sliding Window Log rate limiter backed by Redis ZSET."""

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

    def _key(self, user_id: str) -> str:
        return f"sliding_log:{self.namespace}:{user_id}"

    async def is_allowed(self, user_id: str) -> bool:
        """Determines if a request from user_id is permitted within the sliding window."""
        key = self._key(user_id)
        now = time.time()
        member_id = f"{now}:{uuid.uuid4().hex[:8]}"

        res = await self._script(
            keys=[key],
            args=[self.limit, self.window_seconds, now, member_id, 1],
        )
        return bool(res[0])

    async def remaining(self, user_id: str) -> int:
        """Returns the number of remaining requests without logging an entry."""
        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[self.limit, self.window_seconds, now, "", 0],
        )
        return int(res[1])

    async def get_remaining(self, user_id: str) -> int:
        return await self.remaining(user_id)

    async def retry_after(self, user_id: str) -> int:
        """Returns the number of seconds until the oldest log entry expires."""
        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[self.limit, self.window_seconds, now, "", 0],
        )
        return int(res[2])

    async def get_retry_after(self, user_id: str) -> int:
        return await self.retry_after(user_id)
