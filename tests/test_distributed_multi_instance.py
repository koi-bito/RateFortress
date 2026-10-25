"""Distributed Multi-Instance Integration Tests (Day 43).

Proves that multiple independent FastAPI application server instances sharing a common
Redis backend enforce a single, unified global rate limit across the cluster, preventing
cluster-multiplied quota leaks when traffic is balanced across nodes.
"""

from fastapi import FastAPI
from starlette.testclient import TestClient

from src.middleware.config import EndpointRule
from src.middleware.rate_limit_middleware import RateLimitMiddleware


def _create_app_instance(
    redis_client, algorithm: str = "token_bucket", limit: int = 10
):
    app = FastAPI(title="RateFortressInstance")
    rules = {
        "default": EndpointRule(limit=limit, window_seconds=60, algorithm=algorithm),
        "/api/test": EndpointRule(limit=limit, window_seconds=60, algorithm=algorithm),
    }
    app.add_middleware(RateLimitMiddleware, rules=rules, redis_client=redis_client)

    @app.get("/api/test")
    def test_route():
        return {"message": "success"}

    return app


def test_two_app_instances_shared_token_bucket(redis_client):
    """Verifies two FastAPI instances share a unified Token Bucket rate limit."""
    limit = 10
    app1 = _create_app_instance(redis_client, algorithm="token_bucket", limit=limit)
    app2 = _create_app_instance(redis_client, algorithm="token_bucket", limit=limit)

    client1 = TestClient(app1)
    client2 = TestClient(app2)

    headers = {"X-API-Key": "key_free_abc"}

    # Alternate requests between instance 1 and instance 2
    for i in range(limit):
        active_client = client1 if i % 2 == 0 else client2
        resp = active_client.get("/api/test", headers=headers)
        assert resp.status_code == 200, f"Request {i+1} failed with {resp.status_code}"
        expected_remaining = limit - (i + 1)
        assert int(resp.headers["X-RateLimit-Remaining"]) == expected_remaining

    # 11th request: whether hitting instance 1 or instance 2, MUST be blocked with 429
    resp_blocked_1 = client1.get("/api/test", headers=headers)
    assert resp_blocked_1.status_code == 429
    assert resp_blocked_1.json()["error"] == "rate limit exceeded"

    resp_blocked_2 = client2.get("/api/test", headers=headers)
    assert resp_blocked_2.status_code == 429


def test_two_app_instances_shared_sliding_window_log(redis_client):
    """Verifies two FastAPI instances share a unified Sliding Window Log quota."""
    limit = 6
    app1 = _create_app_instance(
        redis_client, algorithm="sliding_window_log", limit=limit
    )
    app2 = _create_app_instance(
        redis_client, algorithm="sliding_window_log", limit=limit
    )

    client1 = TestClient(app1)
    client2 = TestClient(app2)

    headers = {"X-API-Key": "key_free_abc"}

    for i in range(limit):
        active_client = client1 if i % 2 == 0 else client2
        resp = active_client.get("/api/test", headers=headers)
        assert resp.status_code == 200

    # 7th request blocked across both instances
    resp_7 = client2.get("/api/test", headers=headers)
    assert resp_7.status_code == 429
    assert int(resp_7.headers["X-RateLimit-Remaining"]) == 0


def test_two_app_instances_shared_fixed_window(redis_client):
    """Verifies two FastAPI instances share a unified Fixed Window quota."""
    limit = 4
    app1 = _create_app_instance(redis_client, algorithm="fixed_window", limit=limit)
    app2 = _create_app_instance(redis_client, algorithm="fixed_window", limit=limit)

    client1 = TestClient(app1)
    client2 = TestClient(app2)

    headers = {"X-API-Key": "key_free_abc"}

    for i in range(limit):
        active_client = client1 if i % 2 == 0 else client2
        resp = active_client.get("/api/test", headers=headers)
        assert resp.status_code == 200

    # 5th request blocked on instance 1
    resp_5 = client1.get("/api/test", headers=headers)
    assert resp_5.status_code == 429
