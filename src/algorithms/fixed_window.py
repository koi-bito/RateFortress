"""Fixed Window Counter rate limiting algorithm.

Tracks request counts within fixed-duration time intervals (e.g. 00:00-00:59).
Counters reset upon crossing window boundaries.
"""

import time
from collections import defaultdict


class FixedWindowCounter:
    """Fixed Window Counter rate limiter.

    Attributes:
        limit: Maximum number of allowed requests per window.
        window_seconds: Duration of each window in seconds.
    """

    def __init__(self, limit: int, window_seconds: int):
        if limit <= 0:
            raise ValueError("Limit must be a positive integer.")
        if window_seconds <= 0:
            raise ValueError("Window seconds must be a positive integer.")

        self.limit = limit
        self.window_seconds = window_seconds
        self.counters = defaultdict(int)
        self.window_start = defaultdict(int)

    def is_allowed(self, user_id: str) -> bool:
        """Determines if a request by user_id is allowed in the current window.

        Args:
            user_id: Unique identifier for the client/user.

        Returns:
            True if request is permitted, False if rate limit is exceeded.
        """
        now = time.time()
        current_window = int(now // self.window_seconds)

        if self.window_start[user_id] != current_window:
            # New window: reset counter and update active window ID
            self.window_start[user_id] = current_window
            self.counters[user_id] = 0

        if self.counters[user_id] < self.limit:
            self.counters[user_id] += 1
            return True
        return False

    def get_remaining(self, user_id: str) -> int:
        """Returns the number of remaining requests for user_id in the current window."""
        now = time.time()
        current_window = int(now // self.window_seconds)

        if self.window_start[user_id] != current_window:
            return self.limit
        return max(0, self.limit - self.counters[user_id])

    def get_reset_time(self) -> float:
        """Returns the Unix epoch timestamp when the current window will reset."""
        now = time.time()
        current_window = int(now // self.window_seconds)
        return (current_window + 1) * self.window_seconds
