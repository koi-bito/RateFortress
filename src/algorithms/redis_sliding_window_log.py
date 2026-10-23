"""Redis-backed Sliding Window Log rate limiting algorithm.

Uses Redis Sorted Sets (ZSET) where each member is a unique request identifier/timestamp
and the score is the epoch timestamp (float). Provides exact sliding window precision
without boundary-burst anomalies across distributed systems.
"""

import time
import uuid
from typing import Any


class RedisSlidingWindowLog:
    """Sliding Window Log implemented using Redis Sorted Sets (ZSET)."""

    def __init__(self, redis_client: Any, limit: int, window_seconds: int):
        self.r = redis_client
        self.limit = limit
        self.window_seconds = window_seconds

    def _key(self, user_id: str) -> str:
        return f"sliding_log:{user_id}"

    def is_allowed(self, user_id: str) -> bool:
        """Evaluates whether user_id is permitted to perform a request."""
        key = self._key(user_id)
        now = time.time()
        window_start = now - self.window_seconds

        # Clean old timestamps outside the sliding window
        pipe = self.r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        _, current_count = pipe.execute()

        # Non-atomic check-then-insert (intentionally non-atomic until Lua Day 40)
        if current_count < self.limit:
            # Generate unique member to allow multiple requests within same millisecond
            member_id = f"{now}:{uuid.uuid4().hex[:8]}"
            self.r.zadd(key, {member_id: now})
            self.r.expire(key, self.window_seconds + 1)
            return True

        return False

    def remaining(self, user_id: str) -> int:
        """Returns the number of remaining requests allowed in the current sliding window."""
        key = self._key(user_id)
        now = time.time()
        window_start = now - self.window_seconds

        pipe = self.r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        _, current_count = pipe.execute()

        return max(0, self.limit - current_count)

    def retry_after(self, user_id: str) -> int:
        """Returns the seconds until the oldest request in the window expires."""
        key = self._key(user_id)
        now = time.time()
        window_start = now - self.window_seconds

        # Prune first
        self.r.zremrangebyscore(key, 0, window_start)
        oldest = self.r.zrange(key, 0, 0, withscores=True)

        if not oldest:
            return 1

        _, oldest_timestamp = oldest[0]
        expires_at = oldest_timestamp + self.window_seconds
        retry_seconds = max(1, int(expires_at - now))
        return retry_seconds
