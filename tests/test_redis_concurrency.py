"""Concurrency and atomicity stress tests for Redis-backed rate limiters (Day 42).

Fires simultaneous concurrent requests via ThreadPoolExecutor against the same user key
to verify that Redis atomic operations (INCR) and Lua scripts prevent race conditions,
guaranteeing that EXACTLY the configured limit is admitted with zero over-admission.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from src.algorithms.redis_fixed_window import RedisFixedWindow
from src.algorithms.redis_leaky_bucket import RedisLeakyBucket
from src.algorithms.redis_sliding_window_log import RedisSlidingWindowLog
from src.algorithms.redis_token_bucket import RedisTokenBucket


def _fire_concurrent_requests(
    limiter, user_id: str, count: int = 50
) -> tuple[int, int]:
    """Fires `count` simultaneous requests across threads against `limiter` for `user_id`."""
    allowed = 0
    blocked = 0

    with ThreadPoolExecutor(max_workers=min(32, count)) as executor:
        futures = [executor.submit(limiter.is_allowed, user_id) for _ in range(count)]
        for future in as_completed(futures):
            if future.result():
                allowed += 1
            else:
                blocked += 1

    return allowed, blocked


def test_concurrent_fixed_window_atomicity(redis_client):
    """Verifies RedisFixedWindow INCR atomic operation allows EXACTLY limit requests."""
    limit = 10
    limiter = RedisFixedWindow(redis_client, limit=limit, window_seconds=10)
    user = "user_concurrent_rfw"

    allowed, blocked = _fire_concurrent_requests(limiter, user, count=50)

    assert allowed == limit, f"Expected exactly {limit} allowed, got {allowed}"
    assert blocked == 40, f"Expected exactly 40 blocked, got {blocked}"
    assert limiter.remaining(user) == 0


def test_concurrent_token_bucket_lua_atomicity(redis_client):
    """Verifies RedisTokenBucket Lua script atomicity admits EXACTLY capacity requests."""
    capacity = 10
    limiter = RedisTokenBucket(
        redis_client, capacity=capacity, refill_rate_per_sec=0.01
    )
    user = "user_concurrent_rtb"

    allowed, blocked = _fire_concurrent_requests(limiter, user, count=50)

    assert allowed == capacity, f"Expected exactly {capacity} allowed, got {allowed}"
    assert blocked == 40, f"Expected exactly 40 blocked, got {blocked}"
    assert limiter.remaining(user) == 0


def test_concurrent_leaky_bucket_lua_atomicity(redis_client):
    """Verifies RedisLeakyBucket Lua script atomicity admits EXACTLY capacity requests."""
    capacity = 10
    limiter = RedisLeakyBucket(redis_client, capacity=capacity, leak_rate_per_sec=0.01)
    user = "user_concurrent_rlb"

    allowed, blocked = _fire_concurrent_requests(limiter, user, count=50)

    assert allowed == capacity, f"Expected exactly {capacity} allowed, got {allowed}"
    assert blocked == 40, f"Expected exactly 40 blocked, got {blocked}"
    assert limiter.remaining(user) == 0


def test_concurrent_sliding_window_log_lua_atomicity(redis_client):
    """Verifies Lua-scripted RedisSlidingWindowLog admits EXACTLY limit requests."""
    limit = 10
    limiter = RedisSlidingWindowLog(redis_client, limit=limit, window_seconds=10)
    user = "user_concurrent_rswl"

    allowed, blocked = _fire_concurrent_requests(limiter, user, count=50)

    assert allowed == limit, f"Expected exactly {limit} allowed, got {allowed}"
    assert blocked == 40, f"Expected exactly 40 blocked, got {blocked}"
    assert limiter.remaining(user) == 0
