"""Fixed window counter."""

import time
from collections.abc import Callable

from cachetools import LRUCache


class FixedWindowCounter:
    """Fixed window counter."""

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
        self.counters = LRUCache(maxsize=max_clients)
        self.window_start = LRUCache(maxsize=max_clients)

    def _now(self) -> float:
        return self._now_fn() if self._now_fn is not None else time.time()

    def is_allowed(self, user_id: str) -> bool:
        now = self._now()
        current_window = int(now // self.window_seconds)

        if self.window_start.get(user_id) != current_window:
            # New window: reset counter and update active window ID
            self.window_start[user_id] = current_window
            self.counters[user_id] = 0

        current_count = self.counters.get(user_id, 0)
        if current_count < self.limit:
            self.counters[user_id] = current_count + 1
            return True
        return False

    def get_remaining(self, user_id: str) -> int:
        now = self._now()
        current_window = int(now // self.window_seconds)

        if self.window_start.get(user_id) != current_window:
            return self.limit
        return max(0, self.limit - self.counters.get(user_id, 0))

    def get_reset_time(self) -> float:
        now = self._now()
        current_window = int(now // self.window_seconds)
        return (current_window + 1) * self.window_seconds

    def get_retry_after(self, user_id: str) -> int:
        if self.get_remaining(user_id) > 0:
            return 0
        now = self._now()
        return max(1, int(self.get_reset_time() - now))
