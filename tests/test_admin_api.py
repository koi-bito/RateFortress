"""Unit and Integration Tests for Week 23 Admin API, Dashboard, and Key Store."""

import fakeredis
from fastapi.testclient import TestClient

from src.api.admin import (
    DEFAULT_ADMIN_KEY,
    set_admin_key_manager,
)
from src.api.main import create_app
from src.middleware.config import API_KEYS
from src.middleware.key_manager import APIKeyManager
from src.storage.key_store import MemoryKeyStore, RedisKeyStore, reset_key_store


def setup_fresh_app():
    """Sets up a clean test application with an in-memory key manager."""
    reset_key_store()
    mem_store = MemoryKeyStore()
    manager = APIKeyManager(initial_keys=API_KEYS, key_store=mem_store)
    set_admin_key_manager(manager)
    app = create_app(backend="memory")
    return TestClient(app), manager


def test_admin_auth_rejection_and_success():
    """Verifies that missing or invalid admin credentials are strictly rejected."""
    client, _ = setup_fresh_app()

    # Missing auth
    res_no_auth = client.get("/api/v1/admin/keys")
    assert res_no_auth.status_code == 401
    assert "Unauthorized" in res_no_auth.json()["detail"]

    # Invalid auth
    res_bad_auth = client.get(
        "/api/v1/admin/keys",
        headers={"X-Admin-Key": "completely_wrong_key"},
    )
    assert res_bad_auth.status_code == 401

    # Regular user key used as admin key should fail
    res_user_key = client.get(
        "/api/v1/admin/keys",
        headers={"X-Admin-Key": "key_free_abc"},
    )
    assert res_user_key.status_code == 401

    # Valid X-Admin-Key header
    res_valid = client.get(
        "/api/v1/admin/keys",
        headers={"X-Admin-Key": DEFAULT_ADMIN_KEY},
    )
    assert res_valid.status_code == 200
    assert "keys" in res_valid.json()

    # Valid Bearer token
    res_bearer = client.get(
        "/api/v1/admin/keys",
        headers={"Authorization": f"Bearer {DEFAULT_ADMIN_KEY}"},
    )
    assert res_bearer.status_code == 200


def test_admin_key_crud_lifecycle():
    """Tests the full lifecycle: issue -> get -> patch -> rotate -> revoke -> summary."""
    client, _ = setup_fresh_app()
    admin_headers = {"X-Admin-Key": DEFAULT_ADMIN_KEY}

    # 1. Issue new key
    issue_payload = {
        "tier": "paid",
        "limit_multiplier": 10,
        "description": "Integration Test Key",
    }
    issue_res = client.post("/api/v1/admin/keys", json=issue_payload, headers=admin_headers)
    assert issue_res.status_code == 201
    issue_data = issue_res.json()
    raw_key = issue_data["raw_key"]
    assert raw_key.startswith("rf_paid_")
    assert issue_data["tier"] == "paid"
    assert issue_data["limit_multiplier"] == 10
    assert issue_data["status"] == "active"

    # 2. Get key details
    get_res = client.get(f"/api/v1/admin/keys/{raw_key}", headers=admin_headers)
    assert get_res.status_code == 200
    assert get_res.json()["key_id"] == raw_key

    # 3. Patch key tier to enterprise
    patch_payload = {
        "tier": "enterprise",
        "limit_multiplier": 50,
        "description": "Upgraded to Enterprise",
    }
    patch_res = client.patch(
        f"/api/v1/admin/keys/{raw_key}", json=patch_payload, headers=admin_headers
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["tier"] == "enterprise"
    assert patch_res.json()["limit_multiplier"] == 50

    # 4. Check key usage
    usage_res = client.get(f"/api/v1/admin/keys/{raw_key}/usage", headers=admin_headers)
    assert usage_res.status_code == 200
    assert usage_res.json()["effective_quota_per_minute"] == 5000  # 100 * 50

    # 5. Rotate key with grace period
    rotate_res = client.post(
        f"/api/v1/admin/keys/{raw_key}/rotate",
        json={"grace_period_sec": 1800},
        headers=admin_headers,
    )
    assert rotate_res.status_code == 200
    rotate_data = rotate_res.json()
    new_key = rotate_data["new_key"]
    assert new_key != raw_key
    assert new_key.startswith("rf_enterprise_")
    assert rotate_data["grace_period_sec"] == 1800

    # 6. Revoke the replacement key
    revoke_res = client.delete(f"/api/v1/admin/keys/{new_key}", headers=admin_headers)
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "revoked"

    # 7. Check summary
    summary_res = client.get("/api/v1/admin/summary", headers=admin_headers)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["total_keys"] >= 4
    assert summary["engine_status"] == "healthy"


def test_middleware_rate_limit_integration_with_new_key():
    """Confirms that newly issued keys immediately take effect in rate limit middleware."""
    client, _ = setup_fresh_app()
    admin_headers = {"X-Admin-Key": DEFAULT_ADMIN_KEY}

    # Issue a high-tier enterprise key (50x multiplier)
    issue_res = client.post(
        "/api/v1/admin/keys",
        json={"tier": "enterprise", "limit_multiplier": 50, "description": "High Quota Key"},
        headers=admin_headers,
    )
    raw_key = issue_res.json()["raw_key"]

    # Send request to test endpoint (base limit is 10; with 50x multiplier, limit becomes 500)
    api_res = client.get("/api/test", headers={"X-API-Key": raw_key})
    assert api_res.status_code == 200
    assert "X-RateLimit-Limit" in api_res.headers
    assert int(api_res.headers["X-RateLimit-Limit"]) == 500
    assert int(api_res.headers["X-RateLimit-Remaining"]) >= 498


def test_redis_key_store_persistence_lifecycle():
    """Tests RedisKeyStore CRUD using FakeRedis."""
    fake_server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeRedis(server=fake_server, decode_responses=True)

    store = RedisKeyStore(fake_client)

    # Initial state
    assert store.list_all() == []
    assert not store.exists("test_key_1")

    # Set key
    sample_data = {
        "key_id": "test_key_1",
        "tier": "paid",
        "limit_multiplier": 10,
        "description": "Persistence Test",
    }
    store.set("test_key_1", sample_data)

    assert store.exists("test_key_1")
    retrieved = store.get("test_key_1")
    assert retrieved is not None
    assert retrieved["tier"] == "paid"
    assert retrieved["limit_multiplier"] == 10

    # List all
    all_keys = store.list_all()
    assert len(all_keys) == 1
    assert all_keys[0]["key_id"] == "test_key_1"

    # Delete
    assert store.delete("test_key_1")
    assert not store.exists("test_key_1")
    assert store.get("test_key_1") is None


def test_dashboard_ui_endpoints():
    """Verifies that /admin and /dashboard serve the HTML administrative dashboard."""
    client, _ = setup_fresh_app()

    res_admin = client.get("/admin")
    assert res_admin.status_code == 200
    assert "RateFortress" in res_admin.text
    assert "Multi-Tenant Admin Dashboard" in res_admin.text

    res_dashboard = client.get("/dashboard")
    assert res_dashboard.status_code == 200
    assert "Multi-Tenant Admin Dashboard" in res_dashboard.text
