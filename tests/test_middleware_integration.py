"""Comprehensive integration tests for FastAPI RateLimitMiddleware.

Validates end-to-end ASGI behavior including EndpointTrie prefix matching,
API key tiers, CircuitBreaker fail-open resilience, and RFC rate limit headers.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_default_route_and_headers():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "RateFortress"
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers
    assert "Retry-After" not in response.headers  # RFC 6585/7231
    assert response.headers["X-RateLimit-Tier"] == "anonymous"


def test_trie_prefix_inheritance_enforcement():
    # /api/expensive-endpoint has limit=5
    # Requests to /api/expensive-endpoint/details inherit this limit=5 from the parent prefix
    headers = {"X-Forwarded-For": "192.168.10.50"}

    for _ in range(5):
        resp = client.get("/api/expensive-endpoint", headers=headers)
        assert resp.status_code == 200

    # 6th request to the same prefix is blocked
    blocked_resp = client.get("/api/expensive-endpoint", headers=headers)
    assert blocked_resp.status_code == 429
    assert blocked_resp.headers["X-RateLimit-Remaining"] == "0"
    assert int(blocked_resp.headers["Retry-After"]) >= 1


def test_enterprise_tier_50x_quota():
    # Enterprise API key has 50x multiplier (50 * 5 = 250 requests for expensive endpoint)
    headers = {"X-API-Key": "key_enterprise_999"}
    resp = client.get("/api/expensive-endpoint", headers=headers)

    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Tier"] == "enterprise"
    assert int(resp.headers["X-RateLimit-Limit"]) == 250


def test_circuit_breaker_fail_open_on_limiter_crash():
    """Verifies that if the rate limiter throws an unexpected exception,

    the middleware fails open and returns HTTP 200 rather than dropping customer requests.
    """
    headers = {"X-Forwarded-For": "172.16.0.1"}

    # Mock is_allowed to simulate a sudden storage crash / connection error
    with patch(
        "src.algorithms.sliding_window_log.SlidingWindowLog.is_allowed",
        side_effect=RuntimeError("Storage connection lost"),
    ):
        resp = client.get("/api/expensive-endpoint", headers=headers)
        # Should gracefully fail open and complete the request
        assert resp.status_code == 200


def test_limiter_cache_size_stays_constant_on_parametrized_routes():
    """Bug 6 verification: hitting many distinct concrete paths under one wildcard rule

    must NOT cause unbounded cache growth in middleware._limiter_cache.
    """
    from fastapi import FastAPI

    from src.middleware.config import EndpointRule
    from src.middleware.rate_limit_middleware import RateLimitMiddleware

    custom_app = FastAPI()
    rules = {
        "default": EndpointRule(limit=100, window_seconds=60),
        "/api/items/*": EndpointRule(limit=50, window_seconds=60, algorithm="token_bucket"),
    }
    custom_app.add_middleware(RateLimitMiddleware, rules=rules)

    @custom_app.get("/api/items/{item_id}")
    def get_item(item_id: str):
        return {"item": item_id}

    test_client = TestClient(custom_app)

    # Hit 50 distinct paths under /api/items/
    for i in range(50):
        resp = test_client.get(f"/api/items/{i}")
        assert resp.status_code == 200

    # Inspect middleware instances on the app
    # There should only be 1 cache entry for /api/items/* across all 50 items!
    for mw_instance in [custom_app.middleware_stack]:
        cur = mw_instance
        while hasattr(cur, "app"):
            if isinstance(cur, RateLimitMiddleware):
                assert len(cur._limiter_cache) == 1, (
                    f"Expected 1 cached limiter for /api/items/*, found {len(cur._limiter_cache)}: {list(cur._limiter_cache.keys())}"
                )
                break
            cur = cur.app


def test_two_endpoints_same_algorithm_independent_state(redis_client):
    """Bug 5 verification: two endpoints with different limits using the same algorithm

    must maintain independent state in Redis for the same user via scoped keys.
    """
    from fastapi import FastAPI

    from src.middleware.config import EndpointRule
    from src.middleware.rate_limit_middleware import RateLimitMiddleware

    app_multi = FastAPI()
    rules = {
        "default": EndpointRule(limit=100, window_seconds=60),
        "/api/strict": EndpointRule(limit=2, window_seconds=60, algorithm="token_bucket"),
        "/api/generous": EndpointRule(limit=20, window_seconds=60, algorithm="token_bucket"),
    }
    app_multi.add_middleware(RateLimitMiddleware, rules=rules, redis_client=redis_client)

    @app_multi.get("/api/strict")
    def strict():
        return {"endpoint": "strict"}

    @app_multi.get("/api/generous")
    def generous():
        return {"endpoint": "generous"}

    tc = TestClient(app_multi)
    headers = {"X-API-Key": "key_free_abc"}

    # Exhaust /api/strict (limit=2)
    assert tc.get("/api/strict", headers=headers).status_code == 200
    assert tc.get("/api/strict", headers=headers).status_code == 200
    blocked_strict = tc.get("/api/strict", headers=headers)
    assert blocked_strict.status_code == 429

    # /api/generous (limit=20) for the SAME user must STILL HAVE FULL QUOTA
    gen_resp = tc.get("/api/generous", headers=headers)
    assert gen_resp.status_code == 200
    assert int(gen_resp.headers["X-RateLimit-Remaining"]) == 19, (
        f"Expected 19 remaining for generous route, got {gen_resp.headers.get('X-RateLimit-Remaining')}"
    )


def test_retry_after_absent_on_200_and_present_on_429():
    """Bug 7 verification: Retry-After header must ONLY appear on 429 responses,

    never on successful 200 OK responses with quota remaining.
    """
    headers = {"X-Forwarded-For": "198.51.100.77"}

    # 1. Allowed request -> 200 OK without Retry-After
    res_ok = client.get("/api/test", headers=headers)
    assert res_ok.status_code == 200
    assert "Retry-After" not in res_ok.headers, "Retry-After must NOT be present on HTTP 200"

    # 2. Exhaust /api/expensive-endpoint (limit=5)
    for _ in range(5):
        client.get("/api/expensive-endpoint", headers=headers)

    # 3. Blocked request -> 429 with Retry-After
    res_blocked = client.get("/api/expensive-endpoint", headers=headers)
    assert res_blocked.status_code == 429
    assert "Retry-After" in res_blocked.headers, "Retry-After MUST be present on HTTP 429"
    assert int(res_blocked.headers["Retry-After"]) >= 1

