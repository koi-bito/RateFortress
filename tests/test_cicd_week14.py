"""Tests for Week 14: CI/CD Workflows, Blue-Green Deployment, and Incident Runbook."""

from pathlib import Path

import yaml

from scripts.blue_green_deploy import BlueGreenRouter, run_blue_green_simulation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_github_actions_test_workflow():
    """Validates .github/workflows/test.yml triggers, services, and matrix strategies."""
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "test.yml"
    assert workflow_path.exists(), "test.yml workflow must exist"

    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    triggers = data.get("on") or data.get(True)
    assert triggers is not None
    assert "push" in triggers
    assert "pull_request" in triggers

    jobs = data.get("jobs", {})
    assert "test" in jobs
    test_job = jobs["test"]

    # Verify Python matrix strategy
    strategy = test_job.get("strategy", {})
    matrix = strategy.get("matrix", {})
    py_versions = matrix.get("python-version", [])
    assert "3.11" in py_versions
    assert "3.13" in py_versions

    # Verify Redis service container
    services = test_job.get("services", {})
    assert "redis" in services
    redis_svc = services["redis"]
    assert "redis" in redis_svc["image"]
    assert "6379:6379" in redis_svc["ports"]

    # Verify pytest execution step
    steps = test_job.get("steps", [])
    step_runs = [s.get("run", "") for s in steps]
    assert any("pytest" in r for r in step_runs)
    assert any("ruff" in r for r in step_runs)


def test_github_actions_deploy_workflow():
    """Validates .github/workflows/deploy.yml auto-deploy and post-deploy smoke testing."""
    deploy_path = PROJECT_ROOT / ".github" / "workflows" / "deploy.yml"
    assert deploy_path.exists(), "deploy.yml workflow must exist"

    data = yaml.safe_load(deploy_path.read_text(encoding="utf-8"))
    assert "jobs" in data
    deploy_job = data["jobs"].get("deploy", {})

    steps = deploy_job.get("steps", [])
    step_runs = [s.get("run", "") for s in steps]
    assert any("smoke_test_deployment.py" in r for r in step_runs)


def test_blue_green_router_cutover_and_rollback():
    """Tests the BlueGreenRouter state machine, atomic cutovers, and rollback handling."""
    router = BlueGreenRouter(blue_version="v1.0.0-blue", green_version="v2.0.0-green")

    # Initial state
    assert router.get_active_environment() == "blue"
    assert router.get_active_version() == "v1.0.0-blue"

    # Pre-flight readiness
    blue_probe = router.probe_health("blue")
    green_probe = router.probe_health("green")
    assert blue_probe["healthy"] is True
    assert green_probe["healthy"] is True

    # Initial dispatch
    resp1 = router.dispatch_request("/api/test")
    assert resp1["status"] == 200
    assert resp1["environment"] == "blue"

    # Atomic switch to green
    switched = router.switch_to("green")
    assert switched is True
    assert router.get_active_environment() == "green"
    assert router.get_active_version() == "v2.0.0-green"

    resp2 = router.dispatch_request("/api/test")
    assert resp2["status"] == 200
    assert resp2["environment"] == "green"

    # Rollback to blue
    rolled_back = router.rollback()
    assert rolled_back is True
    assert router.get_active_environment() == "blue"

    resp3 = router.dispatch_request("/api/test")
    assert resp3["status"] == 200
    assert resp3["environment"] == "blue"


def test_blue_green_simulation_execution():
    """Tests that run_blue_green_simulation executes with 0 dropped packets."""
    metrics = run_blue_green_simulation(request_count=30)
    assert metrics["total"] == 30
    assert metrics["failed"] == 0
    assert metrics["blue_serviced"] > 0
    assert metrics["green_serviced"] > 0
    assert metrics["success"] == 30


def test_incident_runbook_completeness():
    """Confirms docs/runbook.md contains severity tiers, procedures, and disaster recovery."""
    runbook_path = PROJECT_ROOT / "docs" / "runbook.md"
    assert runbook_path.exists(), "docs/runbook.md must exist"

    content = runbook_path.read_text(encoding="utf-8")
    assert "P1 — Critical" in content
    assert "P2 — High" in content
    assert "Emergency Rollback Procedures" in content
    assert "Blue-Green Cutover Rollback" in content
    assert "Redis Disaster Recovery" in content
    assert "smoke_test_deployment.py" in content
