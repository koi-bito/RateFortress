"""Unit and integration tests for the Week 12 Algorithm Comparison Engine."""

from pathlib import Path

from starlette.testclient import TestClient

from src.api.compare import TRADEOFFS_CATALOG, generate_synthetic_traffic
from src.api.main import app

client = TestClient(app)


def test_compare_endpoint_json_default():
    """Validates default GET /compare returns structured JSON across all 5 algorithms."""
    response = client.get("/compare")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    data = response.json()
    assert "scenario" in data
    assert "results" in data

    scenario = data["scenario"]
    assert scenario["users"] == 100
    assert scenario["requests_per_user"] == 50
    assert scenario["window_seconds"] == 10
    assert scenario["limit"] == 20  # default 40% of 50
    assert scenario["pattern"] == "uniform"
    assert scenario["total_requests"] == 5000

    results = data["results"]
    assert len(results) == 6

    algo_names = [r["algorithm"] for r in results]
    assert set(algo_names) == {
        "fixed_window",
        "sliding_window_log",
        "sliding_window_counter",
        "token_bucket",
        "leaky_bucket",
        "gcra",
    }

    for r in results:
        # Sum of allowed and blocked must match total scenario requests
        assert r["allowed"] + r["blocked"] == scenario["total_requests"]
        assert round(r["allowed_pct"] + r["blocked_pct"], 1) == 100.0
        assert r["avg_latency_ms"] >= 0.0

        # Validate qualitative tradeoff schema
        tradeoffs = r["tradeoffs"]
        assert len(tradeoffs["accuracy"]) > 10
        assert len(tradeoffs["memory"]) > 5
        assert len(tradeoffs["performance"]) > 10
        assert len(tradeoffs["fairness"]) > 10
        assert len(tradeoffs["ideal_scenario"]) > 10

        # Validate fairness block schema
        fairness = r["fairness"]
        assert fairness["favors"] in ("bursty", "steady", "neutral")


def test_compare_endpoint_custom_query_params():
    """Validates custom user, request count, window, limit, and pattern parameters."""
    response = client.get(
        "/compare?users=15&requests_per_user=20&window=6&limit=8&pattern=uniform"
    )
    assert response.status_code == 200

    data = response.json()
    scenario = data["scenario"]
    assert scenario["users"] == 15
    assert scenario["requests_per_user"] == 20
    assert scenario["window_seconds"] == 6
    assert scenario["limit"] == 8
    assert scenario["total_requests"] == 300

    results = data["results"]
    for r in results:
        assert r["allowed"] + r["blocked"] == 300


def test_compare_endpoint_html_content_negotiation():
    """Validates that Accept: text/html returns the rendered Jinja2 HTML report."""
    response = client.get("/compare", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    body = response.text
    assert "RateFortress Comparison Engine" in body
    assert "Comparative Simulation Matrix" in body
    assert "Fixed Window Counter" in body
    assert "Sliding Window Log" in body
    assert "Sliding Window Counter" in body
    assert "Token Bucket" in body
    assert "Leaky Bucket" in body
    assert "GCRA (Cell Rate)" in body
    assert "Run Simulation ⚡" in body


def test_compare_endpoint_format_query_override():
    """Validates that ?format=html and ?format=json override Accept headers."""
    # Format query param requests HTML even without Accept header
    html_resp = client.get("/compare?format=html")
    assert html_resp.status_code == 200
    assert "text/html" in html_resp.headers["content-type"]

    # Format=json overrides Accept: text/html
    json_resp = client.get("/compare?format=json", headers={"Accept": "text/html"})
    assert json_resp.status_code == 200
    assert json_resp.headers["content-type"].startswith("application/json")


def test_compare_skewed_traffic_fairness():
    """Validates skewed traffic simulation comparing bursty (20%) and steady (80%) clients."""
    response = client.get(
        "/compare?users=20&requests_per_user=25&window=10&limit=10&pattern=skewed"
    )
    assert response.status_code == 200

    data = response.json()
    scenario = data["scenario"]
    assert scenario["pattern"] == "skewed"
    assert scenario["total_requests"] == 500

    results = data["results"]
    for r in results:
        fairness = r["fairness"]
        assert fairness["bursty_users_count"] == 4  # 20 * 0.2
        assert fairness["steady_users_count"] == 16  # 20 - 4
        assert fairness["bursty_users_total"] == 4 * 25
        assert fairness["steady_users_total"] == 16 * 25
        assert fairness["bursty_users_allowed"] <= fairness["bursty_users_total"]
        assert fairness["steady_users_allowed"] <= fairness["steady_users_total"]
        assert fairness["favors"] in ("bursty", "steady", "neutral")


def test_synthetic_traffic_generator_distribution():
    """Tests that generated timestamps stay within window and are chronologically ordered."""
    requests, bursty_count, steady_count = generate_synthetic_traffic(
        users=10, requests_per_user=15, window_seconds=10, pattern="skewed"
    )
    assert len(requests) == 150
    assert bursty_count == 2
    assert steady_count == 8

    # All timestamps must be non-decreasing (sorted)
    timestamps = [t for _, t, _ in requests]
    for i in range(len(timestamps) - 1):
        assert timestamps[i] <= timestamps[i + 1]

    # All timestamps must lie within a sensible window envelope
    assert min(timestamps) >= 0.0
    assert max(timestamps) <= 12.0


def test_compare_endpoint_validation_errors():
    """Validates HTTP 422 for out-of-bounds parameters."""
    # Users < 1
    resp_zero_users = client.get("/compare?users=0")
    assert resp_zero_users.status_code == 422

    # Users > 1000
    resp_max_users = client.get("/compare?users=1001")
    assert resp_max_users.status_code == 422

    # Window < 1
    resp_neg_window = client.get("/compare?window=-5")
    assert resp_neg_window.status_code == 422

    # Invalid pattern
    resp_invalid_pattern = client.get("/compare?pattern=exponential")
    assert resp_invalid_pattern.status_code == 422


def test_tradeoffs_documentation_consistency():
    """Confirms that docs/tradeoffs.md exists and covers all algorithms in catalog."""
    docs_path = Path(__file__).resolve().parents[1] / "docs" / "tradeoffs.md"
    assert docs_path.exists(), "docs/tradeoffs.md must exist"

    content = docs_path.read_text(encoding="utf-8")
    for key in TRADEOFFS_CATALOG:
        assert key in content or key.replace("_", " ") in content.lower()
