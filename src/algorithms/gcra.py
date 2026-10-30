"""Generic Cell Rate Algorithm (GCRA) rate limiter.

GCRA is a leaky bucket / token bucket equivalent based on a virtual scheduling algorithm.
Instead of tracking token counts or logging timestamps, GCRA models traffic arrivals
against a Theoretical Arrival Time (TAT). A request is permitted if its theoretical arrival
time does not exceed the burst tolerance limit.

Used in production by Stripe and Redis Cell.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict


class GCRA:
    """Generic Cell Rate Algorithm (GCRA) rate limiter.

    Attributes:
        limit: Number of requests permitted within the period.
        period: Time window duration in seconds.
        emission_interval: Spacing between cells (period / limit).
        burst_tolerance: Maximum allowable burst offset (emission_interval * (limit - 1)).
    """

    def __init__(self, limit: int, period: float):
        if limit <= 0:
            raise ValueError("Limit must be a positive integer.")
        if period <= 0:
            raise ValueError("Period must be a positive number.")

        self.limit = int(limit)
        self.period = float(period)
        self.emission_interval = self.period / float(self.limit)
        self.burst_tolerance = self.emission_interval * float(self.limit - 1)
        # Maximum horizon into the future that TAT can reach: now + period
        self.burst_horizon = self.burst_tolerance + self.emission_interval  # equals period
        # Theoretical Arrival Time per user_id
        self.tat: dict[str, float] = defaultdict(float)

    def is_allowed(self, user_id: str, cost: int = 1) -> bool:
        """Determines if a request from user_id costing `cost` cells is permitted.

        Args:
            user_id: Unique identifier for the client.
            cost: Number of cell slots requested (default: 1).

        Returns:
            True if allowed, False if throttled.
        """
        if cost <= 0:
            raise ValueError("Requested cost must be positive.")

        now = time.time()
        current_tat = max(now, self.tat[user_id])
        increment = cost * self.emission_interval
        new_tat = current_tat + increment

        if new_tat - now <= self.burst_horizon:
            self.tat[user_id] = new_tat
            return True

        return False

    def get_remaining(self, user_id: str) -> int:
        """Returns estimated remaining requests available within the current period."""
        now = time.time()
        current_tat = self.tat[user_id]
        if current_tat <= now:
            return self.limit

        remaining = math.floor((now + self.burst_horizon - current_tat) / self.emission_interval)
        return max(0, min(self.limit, int(remaining)))

    def get_retry_after(self, user_id: str) -> int:
        """Returns the number of seconds until the client is allowed to send another 1-cost request."""
        now = time.time()
        current_tat = max(now, self.tat[user_id])
        new_tat = current_tat + self.emission_interval
        if new_tat - now <= self.burst_horizon:
            return 0

        delay = (new_tat - now) - self.burst_horizon
        return max(1, math.ceil(delay))
