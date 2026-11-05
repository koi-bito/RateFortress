# DSA practice — not part of application
"""DSA Practice Day: Queues and Concurrency (Day 51)."""

import threading
from collections import deque
from typing import Any


class MyCircularQueue:
    """Fixed-size circular queue (ring buffer) using a fixed array."""

    def __init__(self, k: int):
        if k <= 0:
            raise ValueError("Queue capacity must be positive.")
        self.capacity = k
        self.queue: list[Any] = [None] * k
        self.head = 0
        self.tail = 0
        self.count = 0

    def enQueue(self, value: int) -> bool:
        if self.isFull():
            return False
        self.queue[self.tail] = value
        self.tail = (self.tail + 1) % self.capacity
        self.count += 1
        return True

    def deQueue(self) -> bool:
        if self.isEmpty():
            return False
        self.queue[self.head] = None
        self.head = (self.head + 1) % self.capacity
        self.count -= 1
        return True

    def Front(self) -> int:
        if self.isEmpty():
            return -1
        return self.queue[self.head]

    def Rear(self) -> int:
        if self.isEmpty():
            return -1
        rear_idx = (self.tail - 1) % self.capacity
        return self.queue[rear_idx]

    def isEmpty(self) -> bool:
        return self.count == 0

    def isFull(self) -> bool:
        return self.count == self.capacity


class BoundedBlockingQueue:
    """Thread-safe bounded blocking queue using synchronization primitives."""

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("Queue capacity must be positive.")
        self.capacity = capacity
        self.queue: deque = deque()
        self.lock = threading.Lock()
        self.not_full = threading.Condition(self.lock)
        self.not_empty = threading.Condition(self.lock)

    def enqueue(self, element: int) -> None:
        with self.lock:
            while len(self.queue) >= self.capacity:
                self.not_full.wait()
            self.queue.append(element)
            self.not_empty.notify()

    def dequeue(self) -> int:
        with self.lock:
            while len(self.queue) == 0:
                self.not_empty.wait()
            element = self.queue.popleft()
            self.not_full.notify()
            return element

    def size(self) -> int:
        with self.lock:
            return len(self.queue)


class RecentCounter:
    """Sliding window request counter (LeetCode #933 - Number of Recent Calls)."""

    def __init__(self):
        self.requests: deque[int] = deque()

    def ping(self, t: int) -> int:
        self.requests.append(t)
        min_valid = t - 3000
        while self.requests and self.requests[0] < min_valid:
            self.requests.popleft()
        return len(self.requests)
