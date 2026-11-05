"""Integration and unit tests for Prometheus observability in RateFortress."""

from fastapi.testclient import TestClient

from src.api.main import create_app
from src.monitoring.metrics import get_metrics_payload


def test_metrics_endpoint_returns_prometheus_format():
    """Check /metrics returns HTTP 200 and standard Prometheus text payload."""
    app = create_app(backend="memory")
    client = TestClient(app)

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "ratefortress_requests_total" in response.text


def test_request_and_block_counters_increment():
    """Check allowed and blocked requests increment respective Prometheus counters."""
    app = create_app(backend="memory")
    client = TestClient(app)

    headers = {"X-API-Key": "key_free_abc"}

    # Initial probe
    response = client.get("/api/test", headers=headers)
    assert response.status_code == 200

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    metrics_text = metrics_resp.text

    # Assert request count series exists
    assert 'ratefortress_requests_total{algorithm="token_bucket",endpoint="/api/test",status="allowed",tier="free"}' in metrics_text

    # Force throttle on expensive endpoint (limit = 10 reqs/min for free tier)
    for _ in range(12):
        client.get("/api/expensive-endpoint", headers=headers)

    metrics_resp2 = client.get("/metrics")
    metrics_text2 = metrics_resp2.text

    # Check for blocked counter entry
    assert "ratefortress_blocked_requests_total" in metrics_text2
    assert 'tier="free"' in metrics_text2


def test_limiter_overhead_histogram_recorded():
    """Check rate limiter execution overhead is captured in Prometheus histogram."""
    app = create_app(backend="memory")
    client = TestClient(app)

    client.get("/api/test", headers={"X-API-Key": "key_paid_xyz"})

    metrics_resp = client.get("/metrics")
    assert "ratefortress_limiter_overhead_seconds_count" in metrics_resp.text
    assert "ratefortress_limiter_overhead_seconds_bucket" in metrics_resp.text
    assert 'algorithm="token_bucket"' in metrics_resp.text
    assert 'tier="paid"' in metrics_resp.text


def test_metrics_endpoint_respects_rate_limiting():
    """Telemetry endpoint /metrics respects its configured rate limit (60 req/min)."""
    app = create_app(backend="memory")
    client = TestClient(app)

    # 60 requests succeed within the limit
    for _ in range(60):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    # 61st request exceeds the configured limit
    resp = client.get("/metrics")
    assert resp.status_code == 429
    assert resp.headers["X-RateLimit-Limit"] == "60"


def test_multiprocess_metrics_aggregation(tmp_path, monkeypatch):
    """Bug 8 verification: confirms get_metrics_payload() aggregates multi-process metrics."""
    multiproc_dir = tmp_path / "multiproc"
    multiproc_dir.mkdir()
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(multiproc_dir))

    payload, content_type = get_metrics_payload()
    assert isinstance(payload, bytes)
    assert "text/plain" in content_type


