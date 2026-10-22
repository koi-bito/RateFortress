"""Tests for SlidingWindowCounter rate limiter."""

import time

import pytest

from src.algorithms.sliding_window_counter import SlidingWindowCounter


def test_allows_up_to_limit():
    limiter = SlidingWindowCounter(limit=3, window_seconds=10)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False


def test_resets_after_full_window_pass():
    limiter = SlidingWindowCounter(limit=2, window_seconds=1)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False
    # Wait for more than 1 full window so previous becomes 0
    time.sleep(2.05)
    assert limiter.is_allowed("u1") is True


def test_independent_per_user():
    limiter = SlidingWindowCounter(limit=1, window_seconds=10)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u2") is True
    assert limiter.is_allowed("u1") is False


def test_invalid_inputs():
    with pytest.raises(ValueError, match="Limit must be a positive integer"):
        SlidingWindowCounter(limit=0, window_seconds=10)

    with pytest.raises(ValueError, match="Window seconds must be a positive integer"):
        SlidingWindowCounter(limit=5, window_seconds=0)


def test_weighted_boundary_decay():
    # Test with synthetic time mock to verify the exact mathematical weighting
    from unittest.mock import patch

    limiter = SlidingWindowCounter(limit=10, window_seconds=10)

    # Window 0: at t=5.0, user makes 8 requests
    for _ in range(8):
        with patch("time.time", return_value=5.0):
            assert limiter.is_allowed("u1") is True

    # Window 1: at t=12.0 (2 seconds into 10s window: 20% elapsed, weight of prev is 80%)
    # Estimated = 8 * 0.8 + 0 = 6.4 requests.
    with patch("time.time", return_value=12.0):
        assert limiter.get_estimated_count("u1") == pytest.approx(6.4, rel=1e-2)
        # Limit is 10. Can send 10 - 6.4 = 3.6 -> 4 more requests allowed (k=0,1,2,3 -> counts 6.4, 7.4, 8.4, 9.4)
        assert limiter.is_allowed("u1") is True  # count: 6.4 < 10 -> current becomes 1
        assert limiter.is_allowed("u1") is True  # count: 7.4 < 10 -> current becomes 2
        assert limiter.is_allowed("u1") is True  # count: 8.4 < 10 -> current becomes 3
        assert limiter.is_allowed("u1") is True  # count: 9.4 < 10 -> current becomes 4
        assert limiter.is_allowed("u1") is False  # count: 10.4 >= 10 -> BLOCKED!
