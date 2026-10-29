"""Tests for Week 13: Dockerization, Cloud Deployment, and Smoke Testing Harness."""

import json
from pathlib import Path
from unittest import mock

import yaml
from starlette.testclient import TestClient

from scripts.smoke_test_deployment import run_smoke_tests
from src.api.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_configuration():
    """Validates Dockerfile syntax, multi-stage copying, and healthcheck definitions."""
    dockerfile_path = PROJECT_ROOT / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist at project root"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "FROM python:3." in content and "-slim" in content
    assert "COPY requirements.txt" in content
    assert "COPY src/ src/" in content
    assert "COPY templates/ templates/" in content
    assert "COPY docs/ docs/" in content
    assert "PROMETHEUS_MULTIPROC_DIR" in content
    assert "EXPOSE 8000" in content
    assert "HEALTHCHECK" in content
    assert "/health" in content


def test_docker_compose_configuration():
    """Validates docker-compose.yml services, healthchecks, networks, and volumes."""
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist at project root"

    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    assert "services" in data

    services = data["services"]
    required_services = {"ratefortress", "redis", "prometheus", "grafana", "loki", "promtail"}
    assert required_services.issubset(set(services.keys()))

    # Verify ratefortress container configuration
    app_svc = services["ratefortress"]
    assert "ports" in app_svc and "8000:8000" in app_svc["ports"]
    env = app_svc.get("environment", [])
    assert any("REDIS_HOST=" in item for item in env)
    assert any("RATEFORTRESS_BACKEND=" in item for item in env)
    assert "redis" in str(app_svc.get("depends_on", {}))

    # Verify redis container configuration
    redis_svc = services["redis"]
    assert "healthcheck" in redis_svc
    assert "redis-cli" in str(redis_svc["healthcheck"])
    assert "volatile-lru" in str(redis_svc.get("command", []))

    # Verify networks and volumes
    assert "networks" in data and "ratefortress-net" in data["networks"]
    volumes = data.get("volumes", {})
    assert "redis-data" in volumes
    assert "prometheus-data" in volumes
    assert "grafana-data" in volumes
    assert "loki-data" in volumes


def test_render_blueprint_configuration():
    """Validates render.yaml blueprint schema for Render.com deployment."""
    render_path = PROJECT_ROOT / "render.yaml"
    assert render_path.exists(), "render.yaml must exist at project root"

    data = yaml.safe_load(render_path.read_text(encoding="utf-8"))
    assert "services" in data

    service_names = {s["name"]: s for s in data["services"]}
    assert "ratefortress" in service_names
    assert "ratefortress-redis" in service_names

    app_svc = service_names["ratefortress"]
    assert app_svc["type"] == "web"
    assert app_svc["runtime"] == "docker"
    assert app_svc["healthCheckPath"] == "/health"

    redis_svc = service_names["ratefortress-redis"]
    assert redis_svc["type"] == "redis"
    assert redis_svc["maxmemoryPolicy"] == "volatile-lru"
    assert redis_svc["ipAllowList"] == []


def test_railway_configuration():
    """Validates railway.json deployment specification."""
    railway_path = PROJECT_ROOT / "railway.json"
    assert railway_path.exists(), "railway.json must exist at project root"

    data = json.loads(railway_path.read_text(encoding="utf-8"))
    assert data.get("build", {}).get("builder") == "DOCKERFILE"
    assert data.get("deploy", {}).get("healthcheckPath") == "/health"


def test_cloud_deployment_guide_completeness():
    """Confirms docs/cloud_deployment_guide.md covers all major deployment targets."""
    guide_path = PROJECT_ROOT / "docs" / "cloud_deployment_guide.md"
    assert guide_path.exists(), "docs/cloud_deployment_guide.md must exist"

    content = guide_path.read_text(encoding="utf-8")
    assert "Render.com" in content
    assert "Railway" in content
    assert "AWS EC2" in content
    assert "RATEFORTRESS_BACKEND" in content
    assert "smoke_test_deployment.py" in content


def test_smoke_test_script_with_testclient():
    """Validates that smoke test logic succeeds when run against the active application."""
    client = TestClient(app)

    # Mock make_request using the starlette TestClient
    def mock_make_request(url, headers=None, timeout=10.0):
        # Extract relative path from url
        if "http://localhost:8000" in url:
            path = url.replace("http://localhost:8000", "")
        else:
            path = "/" + url.split("/", 3)[-1] if "/" in url else "/"

        resp = client.get(path, headers=headers or {})
        resp_headers = {k.lower(): v for k, v in resp.headers.items()}
        return resp.status_code, resp_headers, resp.text

    with mock.patch("scripts.smoke_test_deployment.make_request", side_effect=mock_make_request):
        success = run_smoke_tests("http://localhost:8000")
        assert success is True

