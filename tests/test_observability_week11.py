"""Test suite for Week 11 Observability: Grafana, Structured Logging, Tracing & Alerting."""

import json
import logging
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.monitoring.logging_config import JSONLogFormatter, app_logger
from src.monitoring.tracing import in_memory_span_exporter


def test_structured_json_logging_format():
    """Validates that JSONLogFormatter emits valid, parseable JSON with all telemetry keys."""
    formatter = JSONLogFormatter()
    record = logging.LogRecord(
        name="ratefortress",
        level=logging.WARNING,
        pathname="rate_limit_middleware.py",
        lineno=100,
        msg="Rate limit quota exceeded",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-12345"
    record.client_id = "key_paid_xyz"
    record.tier = "paid"
    record.algorithm = "token_bucket"
    record.endpoint = "/api/test"
    record.status_code = 429
    record.latency_ms = 4.2
    record.limiter_overhead_ms = 0.15

    formatted_str = formatter.format(record)
    parsed = json.loads(formatted_str)

    assert parsed["service"] == "ratefortress"
    assert parsed["level"] == "WARNING"
    assert parsed["request_id"] == "req-12345"
    assert parsed["client_id"] == "key_paid_xyz"
    assert parsed["tier"] == "paid"
    assert parsed["algorithm"] == "token_bucket"
    assert parsed["status_code"] == 429
    assert parsed["latency_ms"] == 4.2
    assert parsed["limiter_overhead_ms"] == 0.15
    assert "timestamp" in parsed


def test_opentelemetry_tracing_and_custom_spans():
    """Verifies that OpenTelemetry generates root HTTP spans and custom rate limiter child spans."""
    in_memory_span_exporter.clear()

    app = create_app(backend="memory")
    client = TestClient(app)

    response = client.get("/api/test", headers={"X-API-Key": "key_free_abc"})
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers

    spans = in_memory_span_exporter.get_finished_spans()
    assert len(spans) >= 1

    # Find the custom rate limiter child span
    limiter_spans = [s for s in spans if s.name.startswith("rate_limiter.")]
    assert len(limiter_spans) >= 1

    child_span = limiter_spans[0]
    assert child_span.attributes.get("rate_limit.algorithm") == "token_bucket"
    assert child_span.attributes.get("client.tier") == "free"
    assert child_span.attributes.get("client.id") == "key_free_abc"
    assert child_span.attributes.get("rate_limit.allowed") is True


def test_alert_rules_yaml_syntax_and_schema():
    """Ensures monitoring/alert_rules.yml parses as valid Prometheus alert rule groups."""
    base_dir = Path(__file__).resolve().parent.parent
    alert_rules_file = base_dir / "monitoring" / "alert_rules.yml"
    assert alert_rules_file.exists()

    with open(alert_rules_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "groups" in data
    assert len(data["groups"]) > 0

    group = data["groups"][0]
    alert_names = [rule["alert"] for rule in group.get("rules", [])]
    assert "PaidTierThrottlingSpike" in alert_names
    assert "EnterpriseTenantThrottled" in alert_names
    assert "LimiterDecisionLatencyHigh" in alert_names
    assert "RateFortressGatewayDown" in alert_names


def test_grafana_dashboard_json_validity():
    """Validates that monitoring/grafana_dashboard.json is well-formed with essential panels."""
    base_dir = Path(__file__).resolve().parent.parent
    dashboard_file = base_dir / "monitoring" / "grafana_dashboard.json"
    assert dashboard_file.exists()

    with open(dashboard_file, "r", encoding="utf-8") as f:
        dashboard = json.load(f)

    assert dashboard["title"] == "RateFortress — Production Observability Dashboard"
    assert "panels" in dashboard
    panel_titles = [p.get("title", "") for p in dashboard["panels"]]
    assert any("Throughput" in t for t in panel_titles)
    assert any("Latency" in t for t in panel_titles)
    assert any("Pricing Tier" in t for t in panel_titles)


def test_docker_compose_and_promtail_syntax():
    """Validates docker-compose.yml and promtail.yml configs."""
    base_dir = Path(__file__).resolve().parent.parent

    compose_file = base_dir / "docker-compose.yml"
    assert compose_file.exists()
    with open(compose_file, "r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)
    assert "services" in compose_data
    assert "ratefortress" in compose_data["services"]
    assert "redis" in compose_data["services"]
    assert "prometheus" in compose_data["services"]
    assert "grafana" in compose_data["services"]
    assert "loki" in compose_data["services"]
    assert "promtail" in compose_data["services"]

    promtail_file = base_dir / "monitoring" / "promtail.yml"
    assert promtail_file.exists()
    with open(promtail_file, "r", encoding="utf-8") as f:
        promtail_data = yaml.safe_load(f)
    assert "clients" in promtail_data
    assert "scrape_configs" in promtail_data
