"""Unit tests for the Generic Cell Rate Algorithm (GCRA) pure-Python implementation."""

import time

import pytest

from src.algorithms.gcra import GCRA


def test_allows_up_to_limit():
    """Validates that a fresh client can burst up to the configured limit."""
    limiter = GCRA(limit=5, period=10.0)
    for _ in range(5):
        assert limiter.is_allowed("user1") is True

    # 6th immediate request should be throttled
    assert limiter.is_allowed("user1") is False


def test_refill_and_recovery_over_time():
    """Validates that cell arrival allowance recovers as time elapses."""
    limiter = GCRA(limit=3, period=3.0)  # 1 request per second
    assert limiter.is_allowed("user1") is True
    assert limiter.is_allowed("user1") is True
    assert limiter.is_allowed("user1") is True
    assert limiter.is_allowed("user1") is False

    # Sleep for 1.1 seconds (1 emission interval)
    time.sleep(1.1)
    assert limiter.is_allowed("user1") is True
    # Immediately subsequent request should be blocked again
    assert limiter.is_allowed("user1") is False


def test_retry_after_and_remaining():
    """Validates accurate calculation of remaining capacity and Retry-After delay."""
    limiter = GCRA(limit=4, period=4.0)
    assert limiter.get_remaining("user1") == 4
    assert limiter.get_retry_after("user1") == 0

    assert limiter.is_allowed("user1") is True
    assert limiter.get_remaining("user1") == 3
    assert limiter.get_retry_after("user1") == 0

    assert limiter.is_allowed("user1") is True
    assert limiter.is_allowed("user1") is True
    assert limiter.is_allowed("user1") is True
    assert limiter.get_remaining("user1") == 0

    # Once exhausted, retry_after should be >= 1
    retry = limiter.get_retry_after("user1")
    assert retry >= 1


def test_multi_cost_consumption():
    """Validates consumption of multiple cell units in a single call."""
    limiter = GCRA(limit=5, period=10.0)
    # Consuming 3 out of 5 cells
    assert limiter.is_allowed("user1", cost=3) is True
    # Next cost 3 should exceed the remaining 2 cells
    assert limiter.is_allowed("user1", cost=3) is False
    # But cost 2 should fit exactly
    assert limiter.is_allowed("user1", cost=2) is True
    # Now exhausted
    assert limiter.is_allowed("user1", cost=1) is False


def test_independent_per_user():
    """Validates that different clients have completely isolated rate limits."""
    limiter = GCRA(limit=2, period=10.0)
    assert limiter.is_allowed("alice") is True
    assert limiter.is_allowed("alice") is True
    assert limiter.is_allowed("alice") is False

    # Bob has full quota
    assert limiter.is_allowed("bob") is True
    assert limiter.is_allowed("bob") is True
    assert limiter.is_allowed("bob") is False


def test_invalid_inputs():
    """Validates ValueError raised on invalid parameter initialization."""
    with pytest.raises(ValueError):
        GCRA(limit=0, period=10.0)
    with pytest.raises(ValueError):
        GCRA(limit=5, period=0.0)

    limiter = GCRA(limit=5, period=10.0)
    with pytest.raises(ValueError):
        limiter.is_allowed("user1", cost=0)
