"""Tests for FixedWindowCounter rate limiter."""

import time

import pytest

from src.algorithms.fixed_window import FixedWindowCounter


def test_allows_up_to_limit():
    limiter = FixedWindowCounter(limit=3, window_seconds=10)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False  # 4th request blocked


def test_resets_after_window():
    limiter = FixedWindowCounter(limit=1, window_seconds=1)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False
    time.sleep(1.1)
    assert limiter.is_allowed("u1") is True  # window reset


def test_independent_per_user():
    limiter = FixedWindowCounter(limit=1, window_seconds=10)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u2") is True  # different user has own quota
    assert limiter.is_allowed("u1") is False  # u1 exhausted


def test_remaining_quota_and_reset():
    limiter = FixedWindowCounter(limit=3, window_seconds=10)
    assert limiter.get_remaining("u1") == 3
    limiter.is_allowed("u1")
    assert limiter.get_remaining("u1") == 2
    limiter.is_allowed("u1")
    limiter.is_allowed("u1")
    assert limiter.get_remaining("u1") == 0
    limiter.is_allowed("u1")  # blocked
    assert limiter.get_remaining("u1") == 0
    assert limiter.get_reset_time() > time.time()


def test_invalid_inputs():
    with pytest.raises(ValueError, match="Limit must be a positive integer"):
        FixedWindowCounter(limit=0, window_seconds=10)

    with pytest.raises(ValueError, match="Window seconds must be a positive integer"):
        FixedWindowCounter(limit=5, window_seconds=0)
