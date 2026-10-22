"""Tests for PriorityRequestQueue."""

import random

from src.middleware.priority_queue import PriorityRequestQueue


def test_priority_ordering():
    pq = PriorityRequestQueue()
    pq.push(PriorityRequestQueue.PRIORITY_ANONYMOUS, "anon_1")
    pq.push(PriorityRequestQueue.PRIORITY_PAID, "paid_1")
    pq.push(PriorityRequestQueue.PRIORITY_ENTERPRISE, "ent_1")
    pq.push(PriorityRequestQueue.PRIORITY_FREE, "free_1")

    # Order must be enterprise -> paid -> free -> anonymous
    assert pq.pop()[2] == "ent_1"
    assert pq.pop()[2] == "paid_1"
    assert pq.pop()[2] == "free_1"
    assert pq.pop()[2] == "anon_1"
    assert pq.pop() is None


def test_fifo_ordering_for_equal_priority():
    pq = PriorityRequestQueue()
    pq.push(PriorityRequestQueue.PRIORITY_PAID, "paid_first")
    pq.push(PriorityRequestQueue.PRIORITY_PAID, "paid_second")
    pq.push(PriorityRequestQueue.PRIORITY_PAID, "paid_third")

    assert pq.pop()[2] == "paid_first"
    assert pq.pop()[2] == "paid_second"
    assert pq.pop()[2] == "paid_third"


def test_mixed_overload_simulation():
    """Simulates 50 free-tier and 50 paid-tier requests pushed in random order.

    Confirms all 50 paid requests are dequeued before any free request.
    """
    pq = PriorityRequestQueue()
    requests = []

    for i in range(50):
        requests.append((PriorityRequestQueue.PRIORITY_FREE, f"free_{i}"))
        requests.append((PriorityRequestQueue.PRIORITY_PAID, f"paid_{i}"))

    # Shuffle to simulate random interleaved arrival under load
    random.seed(42)
    random.shuffle(requests)

    for priority, req_id in requests:
        pq.push(priority, req_id)

    assert len(pq) == 100

    # Pop first 50: all must be paid
    popped_first_50 = [pq.pop() for _ in range(50)]
    for item in popped_first_50:
        assert item[0] == PriorityRequestQueue.PRIORITY_PAID
        assert item[2].startswith("paid_")

    # Pop remaining 50: all must be free
    popped_second_50 = [pq.pop() for _ in range(50)]
    for item in popped_second_50:
        assert item[0] == PriorityRequestQueue.PRIORITY_FREE
        assert item[2].startswith("free_")

    assert pq.is_empty()
