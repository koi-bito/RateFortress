"""Redis-backed Sliding Window Counter rate limiting algorithm.

Blends counts from the previous and current fixed windows stored in Redis,
weighted by the elapsed fraction of the active window, delivering an O(1)
memory footprint with boundary-burst smoothing across distributed server nodes.
"""

import time
from typing import Any


class RedisSlidingWindowCounter:
    """Sliding Window Counter backed by Redis key-value storage and pipelines."""

    def __init__(self, redis_client: Any, limit: int, window_seconds: int):
        self.r = redis_client
        self.limit = limit
        self.window_seconds = window_seconds

    def _keys(self, user_id: str, now: float):
        current_id = int(now // self.window_seconds)
        prev_id = current_id - 1
        elapsed_in_window = now % self.window_seconds
        weight_of_previous = 1.0 - (elapsed_in_window / self.window_seconds)

        current_key = f"swc:{user_id}:{current_id}"
        prev_key = f"swc:{user_id}:{prev_id}"
        return current_key, prev_key, weight_of_previous, elapsed_in_window

    def is_allowed(self, user_id: str) -> bool:
        """Evaluates whether user_id is permitted to perform a request."""
        now = time.time()
        current_key, prev_key, weight_prev, _ = self._keys(user_id, now)

        # Pipeline GET both previous and current window counters
        pipe = self.r.pipeline()
        pipe.get(prev_key)
        pipe.get(current_key)
        prev_val, curr_val = pipe.execute()

        prev_count = int(prev_val) if prev_val is not None else 0
        curr_count = int(curr_val) if curr_val is not None else 0

        estimated_count = (prev_count * weight_prev) + curr_count

        if estimated_count < self.limit:
            new_curr = self.r.incr(current_key)
            if new_curr == 1:
                # Key must live through current window + next window to serve as "prev"
                ttl = int(self.window_seconds * 2) + 2
                self.r.expire(current_key, ttl)
            return True

        return False

    def remaining(self, user_id: str) -> int:
        """Returns the estimated remaining quota for user_id in the sliding window."""
        now = time.time()
        current_key, prev_key, weight_prev, _ = self._keys(user_id, now)

        pipe = self.r.pipeline()
        pipe.get(prev_key)
        pipe.get(current_key)
        prev_val, curr_val = pipe.execute()

        prev_count = int(prev_val) if prev_val is not None else 0
        curr_count = int(curr_val) if curr_val is not None else 0

        estimated_count = (prev_count * weight_prev) + curr_count
        return max(0, int(self.limit - estimated_count))

    def retry_after(self, user_id: str) -> int:
        """Returns the estimated seconds until the rate limit will permit a new request."""
        now = time.time()
        _, _, _, elapsed = self._keys(user_id, now)
        remaining_in_window = self.window_seconds - elapsed
        return max(1, int(remaining_in_window))
