"""Sliding Window Counter rate limiting algorithm.

Blends the previous and current fixed window counts, weighted by
how far into the current window the current request is, to approximate
a true sliding window with O(1) memory and O(1) time complexity.
"""

import time
from collections import defaultdict


class SlidingWindowCounter:
    """Sliding Window Counter rate limiter (weighted approximation).

    Attributes:
        limit: Maximum number of allowed requests in the estimated window.
        window_seconds: Duration of each fixed window in seconds.
    """

    def __init__(self, limit: int, window_seconds: int):
        if limit <= 0:
            raise ValueError("Limit must be a positive integer.")
        if window_seconds <= 0:
            raise ValueError("Window seconds must be a positive integer.")

        self.limit = limit
        self.window_seconds = window_seconds
        self.current_window = defaultdict(int)
        self.previous_window = defaultdict(int)
        self.window_id = defaultdict(int)

    def _shift_window(self, user_id: str, current_id: int) -> None:
        if self.window_id[user_id] != current_id:
            windows_passed = current_id - self.window_id[user_id]
            if windows_passed == 1:
                self.previous_window[user_id] = self.current_window[user_id]
            else:
                self.previous_window[user_id] = 0

            self.current_window[user_id] = 0
            self.window_id[user_id] = current_id

    def is_allowed(self, user_id: str) -> bool:
        """Determines if a request by user_id is permitted under the weighted sliding window estimate.

        Args:
            user_id: Unique identifier for the client/user.

        Returns:
            True if request is permitted, False if rate limit is exceeded.
        """
        now = time.time()
        current_id = int(now // self.window_seconds)
        elapsed_in_window = now % self.window_seconds
        weight_of_previous = 1.0 - (elapsed_in_window / self.window_seconds)

        self._shift_window(user_id, current_id)

        estimated_count = (
            self.previous_window[user_id] * weight_of_previous
            + self.current_window[user_id]
        )

        if estimated_count < self.limit:
            self.current_window[user_id] += 1
            return True
        return False

    def get_estimated_count(self, user_id: str) -> float:
        """Returns the current estimated request count for user_id."""
        now = time.time()
        current_id = int(now // self.window_seconds)
        elapsed_in_window = now % self.window_seconds
        weight_of_previous = 1.0 - (elapsed_in_window / self.window_seconds)

        self._shift_window(user_id, current_id)

        return float(
            self.previous_window[user_id] * weight_of_previous
            + self.current_window[user_id]
        )

    def get_remaining(self, user_id: str) -> int:
        """Returns remaining estimated capacity for user_id."""
        estimated = self.get_estimated_count(user_id)
        return max(0, int(self.limit - estimated))

    def get_retry_after(self, user_id: str) -> int:
        """Returns seconds until current window expires and weight resets."""
        if self.get_remaining(user_id) > 0:
            return 0
        now = time.time()
        current_id = int(now // self.window_seconds)
        reset_time = (current_id + 1) * self.window_seconds
        return max(1, int(reset_time - now))
