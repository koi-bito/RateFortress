"""Leaky Bucket rate limiting algorithm.

Requests enter a FIFO queue (the bucket) of fixed capacity and leak out
at a strictly constant rate. If the queue is full, new requests overflow
and are rejected. Unlike Token Bucket, Leaky Bucket enforces a smooth,
constant outflow rate, prohibiting bursts from exceeding queue capacity.
"""

import time
from collections import defaultdict, deque


class LeakyBucket:
    """Leaky Bucket rate limiter.

    Attributes:
        capacity: Maximum number of requests the bucket can hold concurrently.
        leak_rate_per_sec: Rate at which requests leak (process) out of the bucket per second.
    """

    def __init__(self, capacity: int, leak_rate_per_sec: float):
        if capacity <= 0:
            raise ValueError("Capacity must be a positive integer.")
        if leak_rate_per_sec <= 0:
            raise ValueError("Leak rate must be a positive number.")

        self.capacity = capacity
        self.leak_rate = float(leak_rate_per_sec)
        self.queues = defaultdict(deque)
        self.last_leak = defaultdict(time.time)

    def _leak(self, user_id: str, now: float) -> None:
        queue = self.queues[user_id]
        if not queue:
            self.last_leak[user_id] = now
            return

        elapsed = now - self.last_leak[user_id]
        leaked = int(elapsed * self.leak_rate)

        if leaked > 0:
            num_to_remove = min(leaked, len(queue))
            for _ in range(num_to_remove):
                queue.popleft()
            # Advance last_leak by the exact time slice consumed to preserve fractional remainder
            self.last_leak[user_id] += leaked / self.leak_rate

    def is_allowed(self, user_id: str) -> bool:
        """Determines if a request by user_id fits into the bucket queue.

        Args:
            user_id: Unique identifier for the client/user.

        Returns:
            True if request was queued/accepted, False if bucket overflowed.
        """
        now = time.time()
        self._leak(user_id, now)

        queue = self.queues[user_id]
        if len(queue) < self.capacity:
            queue.append(now)
            return True
        return False

    def get_queue_size(self, user_id: str) -> int:
        """Returns the current number of requests in the bucket for user_id."""
        now = time.time()
        self._leak(user_id, now)
        return len(self.queues[user_id])

    def get_remaining_capacity(self, user_id: str) -> int:
        """Returns the remaining empty capacity in the bucket for user_id."""
        return max(0, self.capacity - self.get_queue_size(user_id))
