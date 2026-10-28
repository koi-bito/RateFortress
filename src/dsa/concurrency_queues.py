"""DSA Practice Day: Queues and Concurrency (Day 51).

Implements core queue and synchronization data structures:
1. MyCircularQueue (LeetCode #622 - Design Circular Queue)
2. BoundedBlockingQueue (LeetCode #1188 - Design Bounded Blocking Queue)
3. RecentCounter (LeetCode #933 - Number of Recent Calls)
"""

import threading
from collections import deque
from typing import Any


class MyCircularQueue:
    """Fixed-size circular queue (ring buffer) using a fixed array.

    Avoids dynamic memory reallocation and front-pop array shifting,
    achieving O(1) time complexity for all operations and strict O(K) space.
    """

    def __init__(self, k: int):
        if k <= 0:
            raise ValueError("Queue capacity must be positive.")
        self.capacity = k
        self.queue: list[Any] = [None] * k
        self.head = 0
        self.tail = 0
        self.count = 0

    def enQueue(self, value: int) -> bool:
        """Inserts an element into the circular queue. Returns True if successful."""
        if self.isFull():
            return False
        self.queue[self.tail] = value
        self.tail = (self.tail + 1) % self.capacity
        self.count += 1
        return True

    def deQueue(self) -> bool:
        """Deletes an element from the circular queue. Returns True if successful."""
        if self.isEmpty():
            return False
        self.queue[self.head] = None
        self.head = (self.head + 1) % self.capacity
        self.count -= 1
        return True

    def Front(self) -> int:
        """Gets the front item from the queue. If queue is empty, returns -1."""
        if self.isEmpty():
            return -1
        return self.queue[self.head]

    def Rear(self) -> int:
        """Gets the last item from the queue. If queue is empty, returns -1."""
        if self.isEmpty():
            return -1
        rear_idx = (self.tail - 1) % self.capacity
        return self.queue[rear_idx]

    def isEmpty(self) -> bool:
        """Checks whether the circular queue is empty."""
        return self.count == 0

    def isFull(self) -> bool:
        """Checks whether the circular queue is full."""
        return self.count == self.capacity


class BoundedBlockingQueue:
    """Thread-safe bounded blocking queue using synchronization primitives.

    Directly models request queuing and backpressure at the gateway boundary.
    If the queue is full, calling threads block until space is freed.
    If the queue is empty, consuming worker threads block until items arrive.
    """

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("Queue capacity must be positive.")
        self.capacity = capacity
        self.queue: deque = deque()
        self.lock = threading.Lock()
        self.not_full = threading.Condition(self.lock)
        self.not_empty = threading.Condition(self.lock)

    def enqueue(self, element: int) -> None:
        """Adds an element to the queue, blocking if the queue is full."""
        with self.lock:
            while len(self.queue) >= self.capacity:
                self.not_full.wait()
            self.queue.append(element)
            self.not_empty.notify()

    def dequeue(self) -> int:
        """Removes and returns the front element, blocking if the queue is empty."""
        with self.lock:
            while len(self.queue) == 0:
                self.not_empty.wait()
            element = self.queue.popleft()
            self.not_full.notify()
            return element

    def size(self) -> int:
        """Returns the current number of elements in the queue."""
        with self.lock:
            return len(self.queue)


class RecentCounter:
    """Sliding window request counter (LeetCode #933 - Number of Recent Calls).

    Maintains a rolling 3000ms window log using collections.deque with amortized O(1) eviction.
    """

    def __init__(self):
        self.requests: deque[int] = deque()

    def ping(self, t: int) -> int:
        """Records a new request at millisecond timestamp t and returns count in [t-3000, t]."""
        self.requests.append(t)
        min_valid = t - 3000
        while self.requests and self.requests[0] < min_valid:
            self.requests.popleft()
        return len(self.requests)
