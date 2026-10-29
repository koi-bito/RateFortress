"""Integration tests for FastAPI application and RateLimitMiddleware."""

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_root_and_headers_present():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "RateFortress"

    # Validate rate limit headers exist on standard 200 OK responses
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers
    assert "Retry-After" not in response.headers  # RFC 6585/7231: Retry-After absent on 200 OK
    assert "X-RateLimit-Tier" in response.headers
    assert response.headers["X-RateLimit-Tier"] == "anonymous"


def test_endpoint_rate_limiting_triggers_429():
    # /api/expensive-endpoint has limit=5
    # Anonymous client: 5 requests allowed, 6th must receive HTTP 429
    headers = {"X-Forwarded-For": "192.168.1.100"}

    for _ in range(5):
        resp = client.get("/api/expensive-endpoint", headers=headers)
        assert resp.status_code == 200

    blocked_resp = client.get("/api/expensive-endpoint", headers=headers)
    assert blocked_resp.status_code == 429
    assert blocked_resp.headers["X-RateLimit-Remaining"] == "0"
    assert int(blocked_resp.headers["Retry-After"]) >= 1
    assert "error" in blocked_resp.json()
    assert blocked_resp.json()["error"] == "rate limit exceeded"


def test_paid_api_key_multiplier():
    # Free tier key has 1x multiplier (5 requests for expensive endpoint)
    # Paid tier key has 10x multiplier (50 requests for expensive endpoint)
    free_headers = {"X-API-Key": "key_free_abc"}
    paid_headers = {"X-API-Key": "key_paid_xyz"}

    # Free tier user gets limit of 5
    free_resp = client.get("/api/expensive-endpoint", headers=free_headers)
    assert free_resp.status_code == 200
    assert free_resp.headers["X-RateLimit-Tier"] == "free"
    assert int(free_resp.headers["X-RateLimit-Limit"]) == 5

    # Paid user can execute 10 requests without being blocked
    for _ in range(10):
        resp = client.get("/api/expensive-endpoint", headers=paid_headers)
        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Tier"] == "paid"
        assert int(resp.headers["X-RateLimit-Limit"]) == 50  # 5 * 10


def test_endpoints_enforce_independently():
    headers = {"X-Forwarded-For": "10.0.0.99"}

    # Exceed limit on expensive endpoint (limit=5)
    for _ in range(5):
        assert client.get("/api/expensive-endpoint", headers=headers).status_code == 200
    assert client.get("/api/expensive-endpoint", headers=headers).status_code == 429

    # Another endpoint (/api/test, limit=10) should still be accessible for the same user!
    test_resp = client.get("/api/test", headers=headers)
    assert test_resp.status_code == 200
