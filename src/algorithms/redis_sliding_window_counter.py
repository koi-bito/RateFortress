"""Redis-backed Sliding Window Counter rate limiting algorithm using atomic Lua scripting.

Blends counts from the previous and current fixed windows stored in Redis,
weighted by the elapsed fraction of the active window, delivering an O(1)
memory footprint with boundary-burst smoothing across distributed server nodes.
"""

import time
from pathlib import Path
from typing import Any

LUA_SCRIPT_PATH = Path(__file__).parent / "redis_sliding_window_counter.lua"


class RedisSlidingWindowCounter:
    """Sliding Window Counter backed by Redis atomic Lua scripting."""

    def __init__(
        self,
        redis_client: Any,
        limit: int,
        window_seconds: int,
        namespace: str = "default",
    ):
        if limit <= 0:
            raise ValueError("Limit must be a positive integer.")
        if window_seconds <= 0:
            raise ValueError("Window seconds must be a positive integer.")

        self.r = redis_client
        self.limit = limit
        self.window_seconds = window_seconds
        self.namespace = namespace

        with open(LUA_SCRIPT_PATH, "r", encoding="utf-8") as f:
            script_content = f.read()
        self._script = self.r.register_script(script_content)

    def _keys(self, user_id: str, now: float):
        current_id = int(now // self.window_seconds)
        prev_id = current_id - 1
        elapsed_in_window = now % self.window_seconds
        weight_of_previous = 1.0 - (elapsed_in_window / self.window_seconds)

        current_key = f"swc:{self.namespace}:{user_id}:{current_id}"
        prev_key = f"swc:{self.namespace}:{user_id}:{prev_id}"
        return current_key, prev_key, weight_of_previous, elapsed_in_window

    def is_allowed(self, user_id: str) -> bool:
        """Atomically evaluates whether user_id is permitted to perform a request."""
        now = time.time()
        current_key, prev_key, weight_prev, _ = self._keys(user_id, now)
        ttl = int(self.window_seconds * 2) + 2

        res = self._script(
            keys=[current_key, prev_key],
            args=[self.limit, self.window_seconds, weight_prev, ttl, 1],
        )
        return bool(res[0])

    def remaining(self, user_id: str) -> int:
        """Returns the estimated remaining quota for user_id in the sliding window."""
        now = time.time()
        current_key, prev_key, weight_prev, _ = self._keys(user_id, now)
        ttl = int(self.window_seconds * 2) + 2

        res = self._script(
            keys=[current_key, prev_key],
            args=[self.limit, self.window_seconds, weight_prev, ttl, 0],
        )
        return int(res[1])

    def get_remaining(self, user_id: str) -> int:
        return self.remaining(user_id)

    def retry_after(self, user_id: str) -> int:
        """Returns the estimated seconds until the rate limit will permit a new request."""
        now = time.time()
        current_key, prev_key, weight_prev, _ = self._keys(user_id, now)
        ttl = int(self.window_seconds * 2) + 2

        res = self._script(
            keys=[current_key, prev_key],
            args=[self.limit, self.window_seconds, weight_prev, ttl, 0],
        )
        return int(res[2])

    def get_retry_after(self, user_id: str) -> int:
        return self.retry_after(user_id)
