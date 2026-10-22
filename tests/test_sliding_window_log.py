"""Tests for SlidingWindowLog rate limiter."""

import time

import pytest

from src.algorithms.sliding_window_log import SlidingWindowLog


def test_allows_up_to_limit():
    limiter = SlidingWindowLog(limit=3, window_seconds=10)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False  # 4th request blocked


def test_resets_as_window_slides():
    limiter = SlidingWindowLog(limit=2, window_seconds=1)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False
    # Wait for the first timestamp to fall outside the 1-second rolling window
    time.sleep(1.05)
    assert limiter.is_allowed("u1") is True  # Slot opened up


def test_independent_per_user():
    limiter = SlidingWindowLog(limit=1, window_seconds=10)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u2") is True  # separate user queue
    assert limiter.is_allowed("u1") is False  # u1 exhausted


def test_remaining_and_reset_time():
    limiter = SlidingWindowLog(limit=2, window_seconds=5)
    assert limiter.get_remaining("u1") == 2
    t_start = time.time()
    limiter.is_allowed("u1")
    assert limiter.get_remaining("u1") == 1
    reset_time = limiter.get_reset_time("u1")
    assert reset_time >= t_start + 4.9


def test_invalid_inputs():
    with pytest.raises(ValueError, match="Limit must be a positive integer"):
        SlidingWindowLog(limit=0, window_seconds=10)

    with pytest.raises(ValueError, match="Window seconds must be a positive integer"):
        SlidingWindowLog(limit=5, window_seconds=0)
