"""Tests for LeakyBucket rate limiter."""

import time

import pytest

from src.algorithms.leaky_bucket import LeakyBucket


def test_allows_up_to_capacity():
    limiter = LeakyBucket(capacity=3, leak_rate_per_sec=1.0)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False  # Overflow


def test_leaks_over_time():
    limiter = LeakyBucket(capacity=2, leak_rate_per_sec=5.0)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False

    # After 0.25s, at least 1 item leaks out (0.25 * 5 = 1.25)
    time.sleep(0.25)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False


def test_no_extra_burst_after_idle():
    limiter = LeakyBucket(capacity=2, leak_rate_per_sec=10.0)
    # Even after sitting idle for a while, capacity is strictly bounded by capacity
    time.sleep(0.1)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False


def test_independent_per_user():
    limiter = LeakyBucket(capacity=1, leak_rate_per_sec=1.0)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u2") is True
    assert limiter.is_allowed("u1") is False


def test_invalid_inputs():
    with pytest.raises(ValueError, match="Capacity must be a positive integer"):
        LeakyBucket(capacity=0, leak_rate_per_sec=1.0)

    with pytest.raises(ValueError, match="Leak rate must be a positive number"):
        LeakyBucket(capacity=10, leak_rate_per_sec=0)
