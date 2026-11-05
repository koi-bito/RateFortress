"""Tests for Rate Limiting by Compound Key (Multi-Dimensional Enforcement)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.middleware.config import EndpointRule
from src.middleware.key_manager import APIKeyManager
from src.middleware.rate_limit_middleware import (
    RateLimitMiddleware,
    format_compound_key,
)


def test_format_compound_key():
    """Check multi-dimensional compound key string construction."""
    key = format_compound_key("key_paid_xyz", "/api/v1/resource", "203.0.113.50")
    assert key == "key_paid_xyz:api_v1_resource:203.0.113.50"

    root_key = format_compound_key(None, "/", "127.0.0.1")
    assert root_key == "anon:root:127.0.0.1"


def test_shared_ip_independent_keys_and_shared_ip_limit():
    """Check per-key limits are independent, while the shared per-IP limit applies across both."""
    key_manager = APIKeyManager()
    key_a = key_manager.issue_key(tier="free", limit_multiplier=1, custom_key_id="key_user_a")
    key_b = key_manager.issue_key(tier="free", limit_multiplier=1, custom_key_id="key_user_b")

    rules = {
        "default": EndpointRule(limit=10, window_seconds=60),
        "/api/test": EndpointRule(limit=4, window_seconds=60, algorithm="fixed_window"),
    }

    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        rules=rules,
        key_manager=key_manager,
        global_ip_limit=6,
        global_ip_window=60,
        global_ip_algorithm="fixed_window",
    )

    @app.get("/api/test")
    def get_test():
        return {"status": "ok"}

    client = TestClient(app)

    # 1. User A sends 3 requests (within key limit of 4, within IP limit of 6)
    for _ in range(3):
        res = client.get("/api/test", headers={"X-API-Key": key_a})
        assert res.status_code == 200

    # 2. User B sends 3 requests (within User B's key limit of 4, but reaches IP total of 6)
    for _ in range(3):
        res = client.get("/api/test", headers={"X-API-Key": key_b})
        assert res.status_code == 200

    # At this point:
    # - User A used 3 / 4 key quota (1 remaining)
    # - User B used 3 / 4 key quota (1 remaining)
    # - Shared IP used 6 / 6 global IP quota (0 remaining)

    # 3. User A attempts a 4th request -> blocked by shared global IP quota, not by key quota
    res_a_blocked = client.get("/api/test", headers={"X-API-Key": key_a})
    assert res_a_blocked.status_code == 429
    assert res_a_blocked.headers["X-RateLimit-Scope"] == "ip"
    assert res_a_blocked.headers["X-RateLimit-Limit"] == "6"
    assert "Global IP quota" in res_a_blocked.json()["detail"]

    # 4. User B attempts a 4th request -> also blocked by shared global IP quota
    res_b_blocked = client.get("/api/test", headers={"X-API-Key": key_b})
    assert res_b_blocked.status_code == 429
    assert res_b_blocked.headers["X-RateLimit-Scope"] == "ip"


def test_stricter_per_key_limit_blocks_before_ip_limit():
    """Check if a key's limit is stricter than the IP limit, key limit triggers first."""
    key_manager = APIKeyManager()
    key_a = key_manager.issue_key(tier="free", limit_multiplier=1, custom_key_id="key_solo_a")
    key_b = key_manager.issue_key(tier="free", limit_multiplier=1, custom_key_id="key_solo_b")

    rules = {
        "/api/test": EndpointRule(limit=3, window_seconds=60, algorithm="fixed_window"),
    }

    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        rules=rules,
        key_manager=key_manager,
        global_ip_limit=10,
        global_ip_window=60,
    )

    @app.get("/api/test")
    def get_test():
        return {"status": "ok"}

    client = TestClient(app)

    # User A consumes all 3 key slots
    for _ in range(3):
        res = client.get("/api/test", headers={"X-API-Key": key_a})
        assert res.status_code == 200

    # User A's 4th request exceeds key limit (3), while IP limit (10) still has plenty of quota
    res_key_blocked = client.get("/api/test", headers={"X-API-Key": key_a})
    assert res_key_blocked.status_code == 429
    assert res_key_blocked.headers["X-RateLimit-Scope"] == "key"
    assert res_key_blocked.headers["X-RateLimit-Limit"] == "3"

    # User B from the same IP is NOT blocked because User B's key quota is independent
    res_b = client.get("/api/test", headers={"X-API-Key": key_b})
    assert res_b.status_code == 200


def test_headers_reflect_stricter_dimension():
    """Check X-RateLimit-Remaining and X-RateLimit-Limit track the governing stricter dimension."""
    key_manager = APIKeyManager()
    key = key_manager.issue_key(tier="free", limit_multiplier=1, custom_key_id="key_header_test")

    rules = {
        "/api/test": EndpointRule(limit=5, window_seconds=60, algorithm="fixed_window"),
    }

    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        rules=rules,
        key_manager=key_manager,
        global_ip_limit=2,
        global_ip_window=60,
    )

    @app.get("/api/test")
    def get_test():
        return {"status": "ok"}

    client = TestClient(app)

    # Request 1: Key has 4 remaining (limit 5); IP has 1 remaining (limit 2).
    # IP is stricter (1 < 4), so headers must reflect IP limit
    res1 = client.get("/api/test", headers={"X-API-Key": key})
    assert res1.status_code == 200
    assert res1.headers["X-RateLimit-Remaining"] == "1"
    assert res1.headers["X-RateLimit-Limit"] == "2"
    assert res1.headers["X-RateLimit-Scope"] == "ip"
    assert res1.headers["X-RateLimit-IP-Remaining"] == "1"
    assert res1.headers["X-RateLimit-IP-Limit"] == "2"

    # Request 2: IP exhausts remaining quota
    res2 = client.get("/api/test", headers={"X-API-Key": key})
    assert res2.status_code == 200
    assert res2.headers["X-RateLimit-Remaining"] == "0"
    assert res2.headers["X-RateLimit-Scope"] == "ip"

    # Request 3: Blocked by IP limit
    res3 = client.get("/api/test", headers={"X-API-Key": key})
    assert res3.status_code == 429
    assert res3.headers["X-RateLimit-Scope"] == "ip"

