"""Sliding Window Log rate limiting algorithm.

Stores an exact log of timestamps per user in a collections.deque.
Evicts timestamps older than (now - window_seconds) from the left in O(1) time.
Guarantees exact rate limiting with zero window boundary burst leakage,
at the expense of higher memory footprint: O(N) per user where N is request count.
"""

import time
from collections import defaultdict, deque


class SlidingWindowLog:
    """Sliding Window Log rate limiter.

    Attributes:
        limit: Maximum number of allowed requests within any rolling window.
        window_seconds: Rolling window duration in seconds.
    """

    def __init__(self, limit: int, window_seconds: int):
        if limit <= 0:
            raise ValueError("Limit must be a positive integer.")
        if window_seconds <= 0:
            raise ValueError("Window seconds must be a positive integer.")

        self.limit = limit
        self.window_seconds = window_seconds
        self.logs = defaultdict(deque)

    def is_allowed(self, user_id: str) -> bool:
        """Determines if a request by user_id is permitted within the rolling window.

        Args:
            user_id: Unique identifier for the client/user.

        Returns:
            True if request is permitted, False if rate limit is exceeded.
        """
        now = time.time()
        log = self.logs[user_id]
        cutoff = now - self.window_seconds

        # Drop timestamps older than the rolling window from the front in O(1) per drop
        while log and log[0] <= cutoff:
            log.popleft()

        if len(log) < self.limit:
            log.append(now)
            return True
        return False

    def get_remaining(self, user_id: str) -> int:
        """Returns the number of remaining requests for user_id in the current rolling window."""
        now = time.time()
        log = self.logs[user_id]
        cutoff = now - self.window_seconds

        while log and log[0] <= cutoff:
            log.popleft()

        return max(0, self.limit - len(log))

    def get_reset_time(self, user_id: str) -> float:
        """Returns the Unix epoch timestamp when the oldest request in the window expires.

        If the user has not made any requests, returns the current time.
        """
        now = time.time()
        log = self.logs[user_id]
        cutoff = now - self.window_seconds

        while log and log[0] <= cutoff:
            log.popleft()

        if not log:
            return now
        # Oldest timestamp + window duration is when the earliest slot frees up
        return log[0] + self.window_seconds
