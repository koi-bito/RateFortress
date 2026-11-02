"""Leaky Bucket rate limiting algorithm.

Requests enter a FIFO queue (the bucket) of fixed capacity and leak out
at a strictly constant rate. If the queue is full, new requests overflow
and are rejected. Unlike Token Bucket, Leaky Bucket enforces a smooth,
constant outflow rate, prohibiting bursts from exceeding queue capacity.
"""

import time
from collections import deque
from collections.abc import Callable

from cachetools import LRUCache


class LeakyBucket:
    """Leaky Bucket rate limiter.

    Attributes:
        capacity: Maximum number of requests the bucket can hold concurrently.
        leak_rate_per_sec: Rate at which requests leak (process) out of the bucket per second.
        max_clients: Maximum client entries retained in memory before LRU eviction.
        now_fn: Callable returning current time in seconds (default: time.time).
    """

    def __init__(
        self,
        capacity: int,
        leak_rate_per_sec: float,
        max_clients: int = 100_000,
        now_fn: Callable[[], float] | None = None,
    ):
        if capacity <= 0:
            raise ValueError("Capacity must be a positive integer.")
        if leak_rate_per_sec <= 0:
            raise ValueError("Leak rate must be a positive number.")

        self.capacity = capacity
        self.leak_rate = float(leak_rate_per_sec)
        self.max_clients = max_clients
        self._now_fn = now_fn
        self.now_fn = now_fn or time.time
        self.queues = LRUCache(maxsize=max_clients)
        self.last_leak = LRUCache(maxsize=max_clients)

    def _now(self) -> float:
        return self._now_fn() if self._now_fn is not None else time.time()

    def _leak(self, user_id: str, now: float) -> None:
        queue = self.queues.get(user_id)
        if not queue:
            self.last_leak[user_id] = now
            return

        elapsed = now - self.last_leak.get(user_id, now)
        leaked = int(elapsed * self.leak_rate)

        if leaked > 0:
            num_to_remove = min(leaked, len(queue))
            for _ in range(num_to_remove):
                queue.popleft()
            # Advance last_leak by the exact time slice consumed to preserve fractional remainder
            self.last_leak[user_id] = self.last_leak.get(user_id, now) + leaked / self.leak_rate

    def is_allowed(self, user_id: str) -> bool:
        """Determines if a request by user_id fits into the bucket queue.

        Args:
            user_id: Unique identifier for the client/user.

        Returns:
            True if request was queued/accepted, False if bucket overflowed.
        """
        now = self._now()
        self._leak(user_id, now)

        queue = self.queues.setdefault(user_id, deque())
        if len(queue) < self.capacity:
            queue.append(now)
            self.queues[user_id] = queue
            return True
        return False

    def get_queue_size(self, user_id: str) -> int:
        """Returns the current number of requests in the bucket for user_id."""
        now = self._now()
        self._leak(user_id, now)
        queue = self.queues.get(user_id)
        return len(queue) if queue else 0

    @property
    def limit(self) -> int:
        """Returns the nominal capacity of the bucket."""
        return self.capacity

    def get_remaining(self, user_id: str) -> int:
        """Returns the remaining empty slots in the bucket queue."""
        return self.get_remaining_capacity(user_id)

    def get_retry_after(self, user_id: str) -> int:
        """Returns the number of seconds until a slot leaks out."""
        if self.get_remaining(user_id) > 0:
            return 0
        import math

        return max(1, math.ceil(1.0 / self.leak_rate))

    def get_remaining_capacity(self, user_id: str) -> int:
        """Returns the remaining empty capacity in the bucket for user_id."""
        return max(0, self.capacity - self.get_queue_size(user_id))
