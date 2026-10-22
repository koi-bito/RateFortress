"""Tests for TokenBucket rate limiter."""

import time

import pytest

from src.algorithms.token_bucket import TokenBucket


def test_burst_up_to_capacity():
    limiter = TokenBucket(capacity=5, refill_rate_per_sec=1.0)
    for _ in range(5):
        assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False


def test_refill_over_time():
    limiter = TokenBucket(capacity=2, refill_rate_per_sec=5.0)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False

    # Sleep 0.25s: 0.25 * 5 = 1.25 tokens refilled
    time.sleep(0.25)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False


def test_capacity_cap():
    limiter = TokenBucket(capacity=3, refill_rate_per_sec=100.0)
    time.sleep(0.1)
    # Even after idle time with rapid refill, tokens never exceed capacity
    assert limiter.get_tokens("u1") == 3.0
    for _ in range(3):
        assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False


def test_multi_token_consumption():
    limiter = TokenBucket(capacity=10, refill_rate_per_sec=1.0)
    assert limiter.is_allowed("u1", tokens=6) is True
    assert limiter.is_allowed("u1", tokens=5) is False
    assert limiter.is_allowed("u1", tokens=4) is True


def test_independent_per_user():
    limiter = TokenBucket(capacity=1, refill_rate_per_sec=1.0)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u2") is True
    assert limiter.is_allowed("u1") is False


def test_invalid_inputs():
    with pytest.raises(ValueError, match="Capacity must be a positive integer"):
        TokenBucket(capacity=0, refill_rate_per_sec=1.0)

    with pytest.raises(ValueError, match="Refill rate must be a positive number"):
        TokenBucket(capacity=10, refill_rate_per_sec=0)

    limiter = TokenBucket(capacity=10, refill_rate_per_sec=1.0)
    with pytest.raises(ValueError, match="Requested tokens must be positive"):
        limiter.is_allowed("u1", tokens=0)
