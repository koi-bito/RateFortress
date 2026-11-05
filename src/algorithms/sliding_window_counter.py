"""Sliding Window Counter rate limiting algorithm."""

import time
from collections.abc import Callable

from cachetools import LRUCache


class SlidingWindowCounter:
    """Sliding Window Counter rate limiter (weighted approximation)."""

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
        self.current_window = LRUCache(maxsize=max_clients)
        self.previous_window = LRUCache(maxsize=max_clients)
        self.window_id = LRUCache(maxsize=max_clients)

    def _now(self) -> float:
        return self._now_fn() if self._now_fn is not None else time.time()

    def _shift_window(self, user_id: str, current_id: int) -> None:
        last_win_id = self.window_id.get(user_id, 0)
        if last_win_id != current_id:
            windows_passed = current_id - last_win_id
            if windows_passed == 1:
                self.previous_window[user_id] = self.current_window.get(user_id, 0)
            else:
                self.previous_window[user_id] = 0

            self.current_window[user_id] = 0
            self.window_id[user_id] = current_id

    def is_allowed(self, user_id: str) -> bool:
        now = self._now()
        current_id = int(now // self.window_seconds)
        elapsed_in_window = now % self.window_seconds
        weight_of_previous = 1.0 - (elapsed_in_window / self.window_seconds)

        self._shift_window(user_id, current_id)

        estimated_count = (
            self.previous_window.get(user_id, 0) * weight_of_previous
            + self.current_window.get(user_id, 0)
        )

        if estimated_count < self.limit:
            self.current_window[user_id] = self.current_window.get(user_id, 0) + 1
            return True
        return False

    def get_estimated_count(self, user_id: str) -> float:
        now = self._now()
        current_id = int(now // self.window_seconds)
        elapsed_in_window = now % self.window_seconds
        weight_of_previous = 1.0 - (elapsed_in_window / self.window_seconds)

        self._shift_window(user_id, current_id)

        return float(
            self.previous_window.get(user_id, 0) * weight_of_previous
            + self.current_window.get(user_id, 0)
        )

    def get_remaining(self, user_id: str) -> int:
        estimated = self.get_estimated_count(user_id)
        return max(0, int(self.limit - estimated))

    def get_retry_after(self, user_id: str) -> int:
        if self.get_remaining(user_id) > 0:
            return 0
        now = self._now()
        current_id = int(now // self.window_seconds)
        reset_time = (current_id + 1) * self.window_seconds
        return max(1, int(reset_time - now))
