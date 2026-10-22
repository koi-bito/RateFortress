"""Tiered Priority Request Queue for RateFortress.

Implements an in-memory priority queue using a min-heap (heapq).
During system overload or constrained worker capacity, higher-priority requests
(e.g., enterprise=0, paid=1) are drained and processed before lower-priority ones
(e.g., free=2, anonymous=3).
"""

import heapq
import itertools
from typing import Any


class PriorityRequestQueue:
    """Min-heap priority request queue with FIFO tie-breaking for equal priority levels."""

    # Standard priority levels (lower integer = higher scheduling priority)
    PRIORITY_ENTERPRISE = 0
    PRIORITY_PAID = 1
    PRIORITY_FREE = 2
    PRIORITY_ANONYMOUS = 3

    def __init__(self):
        self.heap: list = []
        self._counter = itertools.count()  # Strict FIFO ordering for equal priority

    def push(self, priority: int, request_id: str, payload: Any = None) -> None:
        """Pushes a request into the priority queue.

        Args:
            priority: Scheduling priority (lower number = higher priority).
            request_id: Unique identifier for the incoming request.
            payload: Optional metadata or request context.
        """
        entry = (priority, next(self._counter), request_id, payload)
        heapq.heappush(self.heap, entry)

    def pop(self) -> tuple[int, int, str, Any] | None:
        """Pops and returns the highest-priority request (lowest priority integer).

        Returns:
            Tuple of (priority, sequence, request_id, payload), or None if empty.
        """
        if self.heap:
            return heapq.heappop(self.heap)
        return None

    def peek(self) -> tuple[int, int, str, Any] | None:
        """Peeks at the next request without removing it."""
        if self.heap:
            return self.heap[0]
        return None

    def __len__(self) -> int:
        return len(self.heap)

    def is_empty(self) -> bool:
        return len(self.heap) == 0
