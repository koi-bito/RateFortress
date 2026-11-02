"""Token Bucket rate limiting algorithm.

Tokens refill into a bucket of fixed capacity at a steady rate per second.
Incoming requests consume tokens. If sufficient tokens are present, the request
is allowed; otherwise, it is blocked. Allows burstiness up to bucket capacity
while enforcing a strict long-term average rate.
"""

import time
from collections.abc import Callable

from cachetools import LRUCache


class TokenBucket:
    """Token Bucket rate limiter.

    Attributes:
        capacity: Maximum number of tokens the bucket can accumulate (burst size).
        refill_rate_per_sec: Steady-state rate at which tokens are added per second.
        max_clients: Maximum client entries retained in memory before LRU eviction.
        now_fn: Callable returning current time in seconds (default: time.time).
    """

    def __init__(
        self,
        capacity: int,
        refill_rate_per_sec: float,
        max_clients: int = 100_000,
        now_fn: Callable[[], float] | None = None,
    ):
        if capacity <= 0:
            raise ValueError("Capacity must be a positive integer.")
        if refill_rate_per_sec <= 0:
            raise ValueError("Refill rate must be a positive number.")

        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate_per_sec)
        self.max_clients = max_clients
        self._now_fn = now_fn
        self.now_fn = now_fn or time.time
        self.tokens = LRUCache(maxsize=max_clients)
        self.last_refill = LRUCache(maxsize=max_clients)

    def _now(self) -> float:
        return self._now_fn() if self._now_fn is not None else time.time()

    def _refill(self, user_id: str, now: float) -> None:
        if user_id not in self.tokens:
            self.tokens[user_id] = self.capacity
            self.last_refill[user_id] = now
            return

        elapsed = now - self.last_refill.get(user_id, now)
        if elapsed > 0:
            added = elapsed * self.refill_rate
            self.tokens[user_id] = min(
                self.capacity, self.tokens.get(user_id, self.capacity) + added
            )
            self.last_refill[user_id] = now

    def is_allowed(self, user_id: str, tokens: int = 1) -> bool:
        """Determines if a request by user_id consuming `tokens` is permitted.

        Args:
            user_id: Unique identifier for the client/user.
            tokens: Number of tokens requested (default: 1).

        Returns:
            True if sufficient tokens were available and consumed, False otherwise.
        """
        if tokens <= 0:
            raise ValueError("Requested tokens must be positive.")

        now = self._now()
        self._refill(user_id, now)

        current_tokens = self.tokens.get(user_id, self.capacity)
        if current_tokens >= tokens:
            self.tokens[user_id] = current_tokens - tokens
            return True
        return False

    @property
    def limit(self) -> int:
        """Returns the nominal limit / capacity of the bucket."""
        return int(self.capacity)

    def get_remaining(self, user_id: str) -> int:
        """Returns available remaining tokens rounded down to an integer."""
        return max(0, int(self.get_tokens(user_id)))

    def get_retry_after(self, user_id: str) -> int:
        """Returns the number of seconds until at least 1 token is refilled."""
        tokens = self.get_tokens(user_id)
        if tokens >= 1.0:
            return 0
        deficit = 1.0 - tokens
        import math

        return max(1, math.ceil(deficit / self.refill_rate))

    def get_tokens(self, user_id: str) -> float:
        """Returns the current available tokens for user_id after accounting for elapsed time."""
        now = self._now()
        self._refill(user_id, now)
        return float(self.tokens.get(user_id, self.capacity))
