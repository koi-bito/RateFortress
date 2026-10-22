"""Token Bucket rate limiting algorithm.

Tokens refill into a bucket of fixed capacity at a steady rate per second.
Incoming requests consume tokens. If sufficient tokens are present, the request
is allowed; otherwise, it is blocked. Allows burstiness up to bucket capacity
while enforcing a strict long-term average rate.
"""

import time
from collections import defaultdict


class TokenBucket:
    """Token Bucket rate limiter.

    Attributes:
        capacity: Maximum number of tokens the bucket can accumulate (burst size).
        refill_rate_per_sec: Steady-state rate at which tokens are added per second.
    """

    def __init__(self, capacity: int, refill_rate_per_sec: float):
        if capacity <= 0:
            raise ValueError("Capacity must be a positive integer.")
        if refill_rate_per_sec <= 0:
            raise ValueError("Refill rate must be a positive number.")

        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate_per_sec)
        self.tokens = defaultdict(lambda: float(capacity))
        self.last_refill = defaultdict(time.time)

    def _refill(self, user_id: str, now: float) -> None:
        elapsed = now - self.last_refill[user_id]
        if elapsed > 0:
            added = elapsed * self.refill_rate
            self.tokens[user_id] = min(self.capacity, self.tokens[user_id] + added)
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

        now = time.time()
        self._refill(user_id, now)

        if self.tokens[user_id] >= tokens:
            self.tokens[user_id] -= tokens
            return True
        return False

    def get_tokens(self, user_id: str) -> float:
        """Returns the current available tokens for user_id after accounting for elapsed time."""
        now = time.time()
        self._refill(user_id, now)
        return self.tokens[user_id]
