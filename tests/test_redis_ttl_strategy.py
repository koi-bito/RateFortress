"""Tests for Redis Key TTL and Expiration Strategy (Day 44).

Audits every algorithm implementation to verify that all created Redis keys
have an active Time-To-Live (TTL > 0), preventing unbounded memory leaks at scale.
"""

from src.algorithms.redis_fixed_window import RedisFixedWindow
from src.algorithms.redis_leaky_bucket import RedisLeakyBucket
from src.algorithms.redis_sliding_window_counter import RedisSlidingWindowCounter
from src.algorithms.redis_sliding_window_log import RedisSlidingWindowLog
from src.algorithms.redis_token_bucket import RedisTokenBucket


def test_fixed_window_key_has_ttl(redis_client):
    limiter = RedisFixedWindow(redis_client, limit=5, window_seconds=10)
    user = "ttl_rfw"
    limiter.is_allowed(user)

    current_window, _ = limiter._get_window_info()
    key = limiter._key(user, current_window)

    ttl = redis_client.ttl(key)
    assert ttl > 0, f"Expected positive TTL for {key}, got {ttl}"
    assert ttl <= 11


def test_sliding_window_counter_key_has_ttl(redis_client):
    limiter = RedisSlidingWindowCounter(redis_client, limit=5, window_seconds=10)
    user = "ttl_rswc"
    limiter.is_allowed(user)

    # Key is swc:{user}:{current_id}
    keys = redis_client.keys(f"swc:{user}:*")
    assert len(keys) == 1
    key = keys[0]

    ttl = redis_client.ttl(key)
    assert ttl > 0, f"Expected positive TTL for {key}, got {ttl}"
    assert ttl <= 22  # window_seconds * 2 + 2


def test_sliding_window_log_key_has_ttl(redis_client):
    limiter = RedisSlidingWindowLog(redis_client, limit=5, window_seconds=10)
    user = "ttl_rswl"
    limiter.is_allowed(user)

    key = limiter._key(user)
    ttl = redis_client.ttl(key)
    assert ttl > 0, f"Expected positive TTL for {key}, got {ttl}"
    assert ttl <= 11


def test_token_bucket_key_has_ttl(redis_client):
    limiter = RedisTokenBucket(redis_client, capacity=10, refill_rate_per_sec=1.0)
    user = "ttl_rtb"
    limiter.is_allowed(user)

    key = limiter._key(user)
    ttl = redis_client.ttl(key)
    assert ttl > 0, f"Expected positive TTL for {key}, got {ttl}"
    assert ttl <= 3600


def test_leaky_bucket_key_has_ttl(redis_client):
    limiter = RedisLeakyBucket(redis_client, capacity=5, leak_rate_per_sec=1.0)
    user = "ttl_rlb"
    limiter.is_allowed(user)

    key = limiter._key(user)
    ttl = redis_client.ttl(key)
    assert ttl > 0, f"Expected positive TTL for {key}, got {ttl}"
    assert ttl <= 3600


def test_zero_immortal_keys_across_all_algorithms(redis_client):
    """Stress test: instantiate and exercise all 5 algorithms, verifying NO key has TTL == -1."""
    limiters = [
        RedisFixedWindow(redis_client, limit=5, window_seconds=10),
        RedisSlidingWindowCounter(redis_client, limit=5, window_seconds=10),
        RedisSlidingWindowLog(redis_client, limit=5, window_seconds=10),
        RedisTokenBucket(redis_client, capacity=5, refill_rate_per_sec=1.0),
        RedisLeakyBucket(redis_client, capacity=5, leak_rate_per_sec=1.0),
    ]

    for i, lim in enumerate(limiters):
        lim.is_allowed(f"audit_user_{i}")

    all_keys = redis_client.keys("*")
    assert len(all_keys) >= 5

    for k in all_keys:
        ttl = redis_client.ttl(k)
        assert ttl > 0, f"Found key without TTL (immortal key leak): {k} (ttl={ttl})"
