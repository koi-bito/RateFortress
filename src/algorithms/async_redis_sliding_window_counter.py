"""Asynchronous Redis-backed Sliding Window Counter rate limiting algorithm.

Smooths window boundaries using a weighted rolling estimate with O(1) memory,
executing non-blocking atomic pipeline calls via redis.asyncio.
"""

import time
from typing import Any


class AsyncRedisSlidingWindowCounter:
    """Non-blocking Sliding Window Counter backed by redis.asyncio pipelines."""

    def __init__(self, redis_client: Any, limit: int, window_seconds: int):
        self.r = redis_client
        self.limit = limit
        self.window_seconds = window_seconds

    def _get_window_info(self, now: float | None = None):
        if now is None:
            now = time.time()
        current_window = int(now // self.window_seconds)
        previous_window = current_window - 1
        elapsed_in_window = now - (current_window * self.window_seconds)
        weight_prev = max(0.0, 1.0 - (elapsed_in_window / self.window_seconds))
        retry_seconds = max(1, int(self.window_seconds - elapsed_in_window))
        return current_window, previous_window, weight_prev, retry_seconds

    def _key(self, user_id: str, window_idx: int) -> str:
        return f"sw_counter:{user_id}:{window_idx}"

    async def is_allowed(self, user_id: str) -> bool:
        """Determines if a request from user_id is permitted based on the weighted count."""
        now = time.time()
        curr_win, prev_win, weight_prev, _ = self._get_window_info(now)
        curr_key = self._key(user_id, curr_win)
        prev_key = self._key(user_id, prev_win)

        ttl = 2 * self.window_seconds + 2

        pipe = self.r.pipeline(transaction=False)
        pipe.get(prev_key)
        pipe.incr(curr_key)
        pipe.expire(curr_key, ttl)
        res = await pipe.execute()

        prev_val = res[0]
        curr_count = res[1]

        prev_count = int(prev_val) if prev_val is not None else 0
        estimated_count = (prev_count * weight_prev) + curr_count

        return estimated_count <= self.limit

    async def remaining(self, user_id: str) -> int:
        """Returns the estimated remaining request quota for user_id."""
        curr_win, prev_win, weight_prev, _ = self._get_window_info()
        curr_key = self._key(user_id, curr_win)
        prev_key = self._key(user_id, prev_win)

        pipe = self.r.pipeline(transaction=False)
        pipe.get(prev_key)
        pipe.get(curr_key)
        res = await pipe.execute()

        prev_val, curr_val = res[0], res[1]
        prev_count = int(prev_val) if prev_val is not None else 0
        curr_count = int(curr_val) if curr_val is not None else 0

        estimated_count = (prev_count * weight_prev) + curr_count
        return max(0, int(self.limit - estimated_count))

    async def get_remaining(self, user_id: str) -> int:
        return await self.remaining(user_id)

    async def retry_after(self, user_id: str) -> int:
        """Returns the seconds remaining until the current window rolls over."""
        _, _, _, retry_seconds = self._get_window_info()
        return retry_seconds

    async def get_retry_after(self, user_id: str) -> int:
        return await self.retry_after(user_id)
