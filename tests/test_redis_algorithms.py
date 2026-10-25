"""Consolidated test suite for all Redis-backed rate limiting algorithms (Day 38).

Covers:
- RedisFixedWindow
- RedisSlidingWindowCounter
- RedisSlidingWindowLog
"""

import time

from src.algorithms.redis_fixed_window import RedisFixedWindow
from src.algorithms.redis_leaky_bucket import RedisLeakyBucket
from src.algorithms.redis_sliding_window_counter import RedisSlidingWindowCounter
from src.algorithms.redis_sliding_window_log import RedisSlidingWindowLog
from src.algorithms.redis_token_bucket import RedisTokenBucket


# ==========================================
# 1. Redis Fixed Window Tests
# ==========================================
def test_redis_fixed_window_enforcement(redis_client):
    limiter = RedisFixedWindow(redis_client, limit=3, window_seconds=10)
    user = "user_rfw"

    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False
    assert limiter.remaining(user) == 0


def test_redis_fixed_window_multi_instance(redis_client):
    inst1 = RedisFixedWindow(redis_client, limit=2, window_seconds=10)
    inst2 = RedisFixedWindow(redis_client, limit=2, window_seconds=10)
    user = "shared_rfw"

    assert inst1.is_allowed(user) is True
    assert inst2.is_allowed(user) is True
    assert inst1.is_allowed(user) is False
    assert inst2.is_allowed(user) is False


# ==========================================
# 2. Redis Sliding Window Counter Tests
# ==========================================
def test_redis_sliding_window_counter_enforcement(redis_client):
    limiter = RedisSlidingWindowCounter(redis_client, limit=3, window_seconds=10)
    user = "user_rswc"

    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False


def test_redis_sliding_window_counter_multi_instance(redis_client):
    inst1 = RedisSlidingWindowCounter(redis_client, limit=4, window_seconds=10)
    inst2 = RedisSlidingWindowCounter(redis_client, limit=4, window_seconds=10)
    user = "shared_rswc"

    assert inst1.is_allowed(user) is True
    assert inst2.is_allowed(user) is True
    assert inst1.is_allowed(user) is True
    assert inst2.is_allowed(user) is True
    assert inst1.is_allowed(user) is False
    assert inst2.is_allowed(user) is False


# ==========================================
# 3. Redis Sliding Window Log Tests
# ==========================================
def test_redis_sliding_window_log_enforcement(redis_client):
    limiter = RedisSlidingWindowLog(redis_client, limit=3, window_seconds=10)
    user = "user_rswl"

    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False
    assert limiter.remaining(user) == 0


def test_redis_sliding_window_log_multi_instance(redis_client):
    inst1 = RedisSlidingWindowLog(redis_client, limit=3, window_seconds=10)
    inst2 = RedisSlidingWindowLog(redis_client, limit=3, window_seconds=10)
    user = "shared_rswl"

    # Alternating requests between server nodes
    assert inst1.is_allowed(user) is True
    assert inst2.is_allowed(user) is True
    assert inst1.is_allowed(user) is True
    # 4th request blocked on both server nodes
    assert inst1.is_allowed(user) is False
    assert inst2.is_allowed(user) is False


def test_redis_sliding_window_log_resets_after_window(redis_client):
    limiter = RedisSlidingWindowLog(redis_client, limit=1, window_seconds=1)
    user = "reset_rswl"

    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False
    time.sleep(1.1)
    assert limiter.is_allowed(user) is True


def test_redis_sliding_window_log_headers(redis_client):
    limiter = RedisSlidingWindowLog(redis_client, limit=5, window_seconds=10)
    user = "headers_rswl"

    assert limiter.remaining(user) == 5
    assert limiter.is_allowed(user) is True
    assert limiter.remaining(user) == 4
    retry = limiter.retry_after(user)
    assert 1 <= retry <= 10


# ==========================================
# 4. Redis Token Bucket Tests (Lua)
# ==========================================
def test_redis_token_bucket_enforcement(redis_client):
    limiter = RedisTokenBucket(redis_client, capacity=3, refill_rate_per_sec=1.0)
    user = "user_rtb"

    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False
    assert limiter.remaining(user) == 0


def test_redis_token_bucket_multi_instance(redis_client):
    inst1 = RedisTokenBucket(redis_client, capacity=3, refill_rate_per_sec=0.1)
    inst2 = RedisTokenBucket(redis_client, capacity=3, refill_rate_per_sec=0.1)
    user = "shared_rtb"

    assert inst1.is_allowed(user) is True
    assert inst2.is_allowed(user) is True
    assert inst1.is_allowed(user) is True
    assert inst1.is_allowed(user) is False
    assert inst2.is_allowed(user) is False


# ==========================================
# 5. Redis Leaky Bucket Tests (Lua)
# ==========================================
def test_redis_leaky_bucket_enforcement(redis_client):
    limiter = RedisLeakyBucket(redis_client, capacity=3, leak_rate_per_sec=1.0)
    user = "user_rlb"

    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False
    assert limiter.remaining(user) == 0


def test_redis_leaky_bucket_multi_instance(redis_client):
    inst1 = RedisLeakyBucket(redis_client, capacity=3, leak_rate_per_sec=0.1)
    inst2 = RedisLeakyBucket(redis_client, capacity=3, leak_rate_per_sec=0.1)
    user = "shared_rlb"

    assert inst1.is_allowed(user) is True
    assert inst2.is_allowed(user) is True
    assert inst1.is_allowed(user) is True
    assert inst1.is_allowed(user) is False
    assert inst2.is_allowed(user) is False
