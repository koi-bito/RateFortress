"""Sliding Window Log rate limiting algorithm.

Stores an exact log of timestamps per user in a collections.deque.
Evicts timestamps older than (now - window_seconds) from the left in O(1) time.
Guarantees exact rate limiting with zero window boundary burst leakage,
at the expense of higher memory footprint: O(N) per user where N is request count.
"""

import time
from collections import deque
from collections.abc import Callable

from cachetools import LRUCache


class SlidingWindowLog:
    """Sliding Window Log rate limiter.

    Attributes:
        limit: Maximum number of allowed requests within any rolling window.
        window_seconds: Rolling window duration in seconds.
        max_clients: Maximum client entries retained in memory before LRU eviction.
        now_fn: Callable returning current time in seconds (default: time.time).
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        max_clients: int = 100_000,
        now_fn: Callable[[], float] | None = None,
    ):
        if limit <= 0:
            raise ValueError("Limit must be a positive integer.")
        if window_seconds <= 0:
            raise ValueError("Window seconds must be a positive integer.")

        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._now_fn = now_fn
        self.now_fn = now_fn or time.time
        self.logs = LRUCache(maxsize=max_clients)

    def _now(self) -> float:
        return self._now_fn() if self._now_fn is not None else time.time()

    def is_allowed(self, user_id: str) -> bool:
        """Determines if a request by user_id is permitted within the rolling window.

        Args:
            user_id: Unique identifier for the client/user.

        Returns:
            True if request is permitted, False if rate limit is exceeded.
        """
        now = self._now()
        log = self.logs.setdefault(user_id, deque())
        cutoff = now - self.window_seconds

        # Drop timestamps older than the rolling window from the front in O(1) per drop
        while log and log[0] <= cutoff:
            log.popleft()

        if len(log) < self.limit:
            log.append(now)
            self.logs[user_id] = log
            return True
        return False

    def get_remaining(self, user_id: str) -> int:
        """Returns the number of remaining requests for user_id in the current rolling window."""
        now = self._now()
        log = self.logs.get(user_id)
        if not log:
            return self.limit
        cutoff = now - self.window_seconds

        while log and log[0] <= cutoff:
            log.popleft()

        return max(0, self.limit - len(log))

    def get_reset_time(self, user_id: str) -> float:
        """Returns the Unix epoch timestamp when the oldest request in the window expires.

        If the user has not made any requests, returns the current time.
        """
        now = self._now()
        log = self.logs.get(user_id)
        if not log:
            return now
        cutoff = now - self.window_seconds

        while log and log[0] <= cutoff:
            log.popleft()

        if not log:
            return now
        # Oldest timestamp + window duration is when the earliest slot frees up
        return log[0] + self.window_seconds

    def get_retry_after(self, user_id: str) -> int:
        """Returns the number of seconds until an existing request timestamp expires."""
        if self.get_remaining(user_id) > 0:
            return 0
        now = self._now()
        return max(1, int(self.get_reset_time(user_id) - now))
