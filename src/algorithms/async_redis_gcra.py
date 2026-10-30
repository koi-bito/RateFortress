"""Asynchronous Redis-backed GCRA rate limiting algorithm using atomic Lua scripting.

Guarantees full atomicity across distributed application instances executing on redis.asyncio.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

LUA_SCRIPT_PATH = Path(__file__).parent / "redis_gcra.lua"


class AsyncRedisGCRA:
    """Distributed asynchronous GCRA rate limiter powered by Redis Lua."""

    def __init__(
        self,
        redis_client: Any,
        limit: int,
        period: float,
        namespace: str = "default",
    ):
        if limit <= 0:
            raise ValueError("Limit must be a positive integer.")
        if period <= 0:
            raise ValueError("Period must be a positive number.")

        self.r = redis_client
        self.limit_val = int(limit)
        self.period = float(period)
        self.emission_interval = self.period / float(self.limit_val)
        self.burst_tolerance = self.emission_interval * float(self.limit_val - 1)
        self.namespace = namespace

        with open(LUA_SCRIPT_PATH, "r", encoding="utf-8") as f:
            script_content = f.read()
        self._script = self.r.register_script(script_content)

    def _key(self, user_id: str) -> str:
        return f"gcra:{self.namespace}:{user_id}"

    async def is_allowed(self, user_id: str, cost: int = 1) -> bool:
        """Evaluates whether user_id is permitted to consume `cost` units asynchronously."""
        if cost <= 0:
            raise ValueError("Requested cost must be positive.")

        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[
                self.emission_interval,
                self.burst_tolerance,
                now,
                cost,
                self.limit_val,
            ],
        )
        return bool(res[0])

    async def remaining(self, user_id: str) -> int:
        """Returns remaining permitted requests without consuming quota."""
        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[
                self.emission_interval,
                self.burst_tolerance,
                now,
                0,
                self.limit_val,
            ],
        )
        return int(res[1])

    async def get_remaining(self, user_id: str) -> int:
        """Alias for `remaining`."""
        return await self.remaining(user_id)

    async def retry_after(self, user_id: str) -> int:
        """Returns seconds until next cell request is permitted."""
        key = self._key(user_id)
        now = time.time()
        res = await self._script(
            keys=[key],
            args=[
                self.emission_interval,
                self.burst_tolerance,
                now,
                0,
                self.limit_val,
            ],
        )
        return int(res[2])

    async def get_retry_after(self, user_id: str) -> int:
        """Alias for `retry_after`."""
        return await self.retry_after(user_id)

    @property
    def limit(self) -> int:
        """Returns the nominal capacity/limit."""
        return self.limit_val
