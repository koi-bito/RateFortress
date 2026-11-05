"""Tests for Graceful Shutdown Handling."""

import asyncio

import httpx
import pytest

from src.api.main import create_app


@pytest.mark.asyncio
async def test_in_flight_request_survives_shutdown_while_new_request_rejected():
    """Check in-flight requests survive mid-request shutdown, while new requests are rejected."""
    app = create_app(backend="memory")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Start an in-flight request that takes 0.3 seconds to finish
        slow_task = asyncio.create_task(client.get("/api/slow-request?delay=0.3"))

        # 2. Wait 0.05s to check the slow request has entered the middleware and is actively executing
        await asyncio.sleep(0.05)

        # 3. Simulate SIGTERM / shutdown signal arrival
        app.state.is_shutting_down = True
        middleware = getattr(app.state, "rate_limit_middleware", None)
        if middleware:
            middleware.is_shutting_down = True

        # 4. Attempt a NEW request to /api/test during the shutdown window
        new_res = await client.get("/api/test")
        assert new_res.status_code == 503
        assert new_res.headers["Retry-After"] == "5"
        assert "Server is shutting down" in new_res.json()["detail"]

        # 5. Await the original in-flight request; it must complete successfully!
        slow_res = await slow_task
        assert slow_res.status_code == 200
        assert slow_res.json()["status"] == "completed"
        assert slow_res.json()["delayed_seconds"] == 0.3


@pytest.mark.asyncio
async def test_readiness_and_liveness_probes_during_shutdown():
    """Check readiness returns 503 (detour traffic) while liveness returns 200 (allow drain)."""
    app = create_app(backend="memory")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Pre-shutdown
        res_ready_before = await client.get("/health/ready")
        assert res_ready_before.status_code == 200

        # Initiate shutdown
        app.state.is_shutting_down = True

        # Liveness check (/health) must still return 200
        res_live = await client.get("/health")
        assert res_live.status_code == 200
        assert res_live.json() == {"status": "healthy"}

        # Readiness check (/health/ready) must return 503
        res_ready = await client.get("/health/ready")
        assert res_ready.status_code == 503
        assert res_ready.json()["status"] == "not_ready"
        assert res_ready.json()["reason"] == "shutting_down"


@pytest.mark.asyncio
async def test_middleware_drain_in_flight():
    """Tests that drain_in_flight waits for _active_requests to reach 0."""
    app = create_app(backend="memory")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Warm middleware registration
        await client.get("/health")
        middleware = getattr(app.state, "rate_limit_middleware", None)
        assert middleware is not None

        # Check drain on idle middleware succeeds immediately
        drained = await middleware.drain_in_flight(timeout=1.0)
        assert drained is True
        assert middleware._active_requests == 0

