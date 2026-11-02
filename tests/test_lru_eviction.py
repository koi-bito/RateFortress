"""Tests for LRU cache eviction in pure-Python rate limiters (Fix 14)."""

from src.algorithms.fixed_window import FixedWindowCounter
from src.algorithms.gcra import GCRA
from src.algorithms.leaky_bucket import LeakyBucket
from src.algorithms.sliding_window_counter import SlidingWindowCounter
from src.algorithms.sliding_window_log import SlidingWindowLog
from src.algorithms.token_bucket import TokenBucket


def test_fixed_window_lru_eviction():
    limiter = FixedWindowCounter(limit=2, window_seconds=60, max_clients=2)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u2") is True
    assert "u1" in limiter.counters
    assert "u2" in limiter.counters

    # Adding u3 evicts LRU (u1)
    assert limiter.is_allowed("u3") is True
    assert "u1" not in limiter.counters
    assert "u2" in limiter.counters
    assert "u3" in limiter.counters


def test_sliding_window_log_lru_eviction():
    limiter = SlidingWindowLog(limit=2, window_seconds=60, max_clients=2)
    limiter.is_allowed("u1")
    limiter.is_allowed("u2")
    assert "u1" in limiter.logs
    limiter.is_allowed("u3")
    assert "u1" not in limiter.logs


def test_sliding_window_counter_lru_eviction():
    limiter = SlidingWindowCounter(limit=2, window_seconds=60, max_clients=2)
    limiter.is_allowed("u1")
    limiter.is_allowed("u2")
    assert "u1" in limiter.current_window
    limiter.is_allowed("u3")
    assert "u1" not in limiter.current_window


def test_token_bucket_lru_eviction():
    limiter = TokenBucket(capacity=2, refill_rate_per_sec=1.0, max_clients=2)
    limiter.is_allowed("u1")
    limiter.is_allowed("u2")
    assert "u1" in limiter.tokens
    limiter.is_allowed("u3")
    assert "u1" not in limiter.tokens


def test_leaky_bucket_lru_eviction():
    limiter = LeakyBucket(capacity=2, leak_rate_per_sec=1.0, max_clients=2)
    limiter.is_allowed("u1")
    limiter.is_allowed("u2")
    assert "u1" in limiter.queues
    limiter.is_allowed("u3")
    assert "u1" not in limiter.queues


def test_gcra_lru_eviction():
    limiter = GCRA(limit=2, period=60.0, max_clients=2)
    limiter.is_allowed("u1")
    limiter.is_allowed("u2")
    assert "u1" in limiter.tat
    limiter.is_allowed("u3")
    assert "u1" not in limiter.tat

