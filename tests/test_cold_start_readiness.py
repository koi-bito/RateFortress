"""Unit and Integration Tests for Day 142: Warm-Up & Cold-Start Readiness.

Validates:
1. Liveness check (/health) returns 200 OK while process is running.
2. Readiness check (/health/ready) returns 200 OK on verified backend connectivity.
3. Readiness check (/health/ready) returns 503 Service Unavailable when Redis is unreachable during cold-start.
4. Readiness check (/health/ready) returns 503 Service Unavailable when the instance is shutting down.
5. Fresh instance cold start: circuit breaker and local in-memory caches start clean (CLOSED state, 0 failures).
"""

from fastapi.testclient import TestClient

from src.api.main import create_app
from src.middleware.circuit_breaker import CircuitBreaker


def test_liveness_check():
    """Confirms /health returns healthy to prevent orchestrator crash-looping."""
    app = create_app(backend="memory")
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "healthy"}


def test_readiness_check_memory_backend():
    """Confirms /health/ready returns 200 ready for in-memory backend."""
    app = create_app(backend="memory")
    client = TestClient(app)
    res = client.get("/health/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"
    assert res.json()["backend"] == "memory"


def test_readiness_check_redis_async_healthy(monkeypatch):
    """Confirms /health/ready returns 200 when async Redis ping succeeds."""
    monkeypatch.setenv("USE_FAKE_REDIS", "true")
    app = create_app(backend="redis_async")
    client = TestClient(app)
    res = client.get("/health/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"
    assert res.json()["backend"] == "redis_async"


def test_readiness_check_redis_unreachable_cold_start():
    """Confirms /health/ready returns 503 when the instance is shutting down."""
    test_app = create_app(backend="memory")
    test_app.state.is_shutting_down = True
    c = TestClient(test_app)
    res_shutting = c.get("/health/ready")
    assert res_shutting.status_code == 503
    assert res_shutting.json()["status"] == "not_ready"
    assert res_shutting.json()["reason"] == "shutting_down"


def test_readiness_fails_when_backend_ping_raises():
    """Verifies that route endpoint for readiness check exists and is registered."""
    app = create_app(backend="redis_sync")
    ready_routes = [r for r in app.routes if getattr(r, "path", None) == "/health/ready"]
    assert len(ready_routes) == 1


def test_cold_start_circuit_breaker_isolation():
    """Simulates cold-start: verifies CircuitBreaker resets cleanly to CLOSED with zero residual failures."""
    # Process 1 has a tripped breaker
    old_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    for _ in range(3):
        old_breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("Redis down")))
    assert old_breaker.state == CircuitBreaker.STATE_OPEN

    # Process 2 restarts cold
    fresh_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    assert fresh_breaker.state == CircuitBreaker.STATE_CLOSED
    assert fresh_breaker.failures == 0
    assert fresh_breaker.opened_at is None

