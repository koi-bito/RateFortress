"""Unit tests for Day 51 DSA Queue and Concurrency problems.

Tests:
1. MyCircularQueue (LeetCode #622)
2. BoundedBlockingQueue (LeetCode #1188)
3. RecentCounter (LeetCode #933)
"""

import threading
import time

from src.dsa.concurrency_queues import (
    BoundedBlockingQueue,
    MyCircularQueue,
    RecentCounter,
)


def test_circular_queue_basic_operations():
    q = MyCircularQueue(3)
    assert q.isEmpty() is True
    assert q.isFull() is False
    assert q.Front() == -1
    assert q.Rear() == -1

    assert q.enQueue(1) is True
    assert q.enQueue(2) is True
    assert q.enQueue(3) is True
    assert q.enQueue(4) is False  # Queue is full

    assert q.isFull() is True
    assert q.Rear() == 3
    assert q.Front() == 1

    assert q.deQueue() is True  # Removes 1
    assert q.Front() == 2
    assert q.enQueue(4) is True  # Wrap-around insert
    assert q.Rear() == 4
    assert q.isFull() is True

    assert q.deQueue() is True  # Removes 2
    assert q.deQueue() is True  # Removes 3
    assert q.deQueue() is True  # Removes 4
    assert q.isEmpty() is True
    assert q.deQueue() is False


def test_recent_counter_sliding_window():
    rc = RecentCounter()
    assert rc.ping(1) == 1
    assert rc.ping(100) == 2
    assert rc.ping(3001) == 3
    assert rc.ping(3002) == 3  # Timestamp 1 is now expired (3002 - 3000 = 2 > 1)
    assert rc.ping(7000) == 1  # 100, 3001, 3002 all expired (< 4000)


def test_bounded_blocking_queue_single_thread():
    bbq = BoundedBlockingQueue(2)
    assert bbq.size() == 0
    bbq.enqueue(10)
    bbq.enqueue(20)
    assert bbq.size() == 2
    assert bbq.dequeue() == 10
    assert bbq.dequeue() == 20
    assert bbq.size() == 0


def test_bounded_blocking_queue_multithreaded():
    bbq = BoundedBlockingQueue(5)
    produced = []
    consumed = []
    total_items = 50

    def producer():
        for i in range(total_items):
            bbq.enqueue(i)
            produced.append(i)
            time.sleep(0.001)

    def consumer():
        for _ in range(total_items):
            val = bbq.dequeue()
            consumed.append(val)
            time.sleep(0.001)

    t_prod = threading.Thread(target=producer)
    t_cons = threading.Thread(target=consumer)

    t_prod.start()
    t_cons.start()

    t_prod.join(timeout=5.0)
    t_cons.join(timeout=5.0)

    assert len(produced) == total_items
    assert len(consumed) == total_items
    assert produced == consumed
    assert bbq.size() == 0
