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
from collections.abc import Callable

from cachetools import LRUCache


class GCRA:
    """Generic Cell Rate Algorithm (GCRA) rate limiter.

    Attributes:
        limit: Number of requests permitted within the period.
        period: Time window duration in seconds.
        emission_interval: Spacing between cells (period / limit).
        burst_tolerance: Maximum allowable burst offset (emission_interval * (limit - 1)).
        max_clients: Maximum client entries retained in memory before LRU eviction.
        now_fn: Callable returning current time in seconds (default: time.time).
    """

    def __init__(
        self,
        limit: int,
        period: float,
        max_clients: int = 100_000,
        now_fn: Callable[[], float] | None = None,
    ):
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
        self.max_clients = max_clients
        self._now_fn = now_fn
        self.now_fn = now_fn or time.time
        # Theoretical Arrival Time per user_id
        self.tat: LRUCache = LRUCache(maxsize=max_clients)

    def _now(self) -> float:
        return self._now_fn() if self._now_fn is not None else time.time()

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

        now = self._now()
        current_tat = max(now, self.tat.get(user_id, 0.0))
        increment = cost * self.emission_interval
        new_tat = current_tat + increment

        if new_tat - now <= self.burst_horizon:
            self.tat[user_id] = new_tat
            return True

        return False

    def get_remaining(self, user_id: str) -> int:
        """Returns estimated remaining requests available within the current period."""
        now = self._now()
        current_tat = self.tat.get(user_id, 0.0)
        if current_tat <= now:
            return self.limit

        remaining = math.floor((now + self.burst_horizon - current_tat) / self.emission_interval)
        return max(0, min(self.limit, int(remaining)))

    def get_retry_after(self, user_id: str) -> int:
        """Returns the number of seconds until the client is allowed to send another 1-cost request."""
        now = self._now()
        current_tat = max(now, self.tat.get(user_id, 0.0))
        new_tat = current_tat + self.emission_interval
        if new_tat - now <= self.burst_horizon:
            return 0

        delay = (new_tat - now) - self.burst_horizon
        return max(1, math.ceil(delay))
