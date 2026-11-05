"""Tiered Priority Request Queue for RateFortress."""

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
        entry = (priority, next(self._counter), request_id, payload)
        heapq.heappush(self.heap, entry)

    def pop(self) -> tuple[int, int, str, Any] | None:
        if self.heap:
            return heapq.heappop(self.heap)
        return None

    def peek(self) -> tuple[int, int, str, Any] | None:
        if self.heap:
            return self.heap[0]
        return None

    def __len__(self) -> int:
        return len(self.heap)

    def is_empty(self) -> bool:
        return len(self.heap) == 0
