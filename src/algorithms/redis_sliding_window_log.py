"""Redis-backed Sliding Window Log rate limiting algorithm using atomic Lua scripting.

Uses Redis Sorted Sets (ZSET) where each member is a unique request identifier/timestamp
and the score is the epoch timestamp (float). Executes pruning, cardinality checking,
and request insertion in a single atomic Lua script to eliminate race conditions under
high concurrent load across distributed systems.
"""

import time
import uuid
from pathlib import Path
from typing import Any

LUA_SCRIPT_PATH = Path(__file__).parent / "redis_sliding_window_log.lua"


class RedisSlidingWindowLog:
    """Sliding Window Log implemented using Redis Sorted Sets (ZSET) and atomic Lua script."""

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

    def _key(self, user_id: str) -> str:
        return f"sliding_log:{self.namespace}:{user_id}"

    def is_allowed(self, user_id: str) -> bool:
        """Atomically evaluates whether user_id is permitted to perform a request."""
        key = self._key(user_id)
        now = time.time()
        member_id = f"{now}:{uuid.uuid4().hex[:8]}"

        res = self._script(
            keys=[key],
            args=[self.limit, self.window_seconds, now, member_id, 1],
        )
        return bool(res[0])

    def remaining(self, user_id: str) -> int:
        """Returns the remaining request quota in the active sliding window."""
        key = self._key(user_id)
        now = time.time()
        res = self._script(
            keys=[key],
            args=[self.limit, self.window_seconds, now, "", 0],
        )
        return int(res[1])

    def get_remaining(self, user_id: str) -> int:
        """Alias for `remaining`."""
        return self.remaining(user_id)

    def retry_after(self, user_id: str) -> int:
        """Returns the seconds until the oldest request in the window expires."""
        key = self._key(user_id)
        now = time.time()
        res = self._script(
            keys=[key],
            args=[self.limit, self.window_seconds, now, "", 0],
        )
        return int(res[2])

    def get_retry_after(self, user_id: str) -> int:
        """Alias for `retry_after`."""
        return self.retry_after(user_id)
