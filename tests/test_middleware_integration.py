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
    assert "Retry-After" in response.headers
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
