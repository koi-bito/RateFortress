"""Live Deployment Smoke Testing Harness for RateFortress.

Validates that a containerized or cloud-deployed RateFortress gateway instance
is fully operational across health checks, root metadata, Prometheus telemetry,
the Algorithm Comparison Engine (JSON & HTML), and active rate-limit enforcement.

Usage:
    python scripts/smoke_test_deployment.py [--url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def make_request(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, str], str]:
    """Sends HTTP GET request returning (status_code, headers_dict, body_str)."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp_headers, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        resp_headers = {k.lower(): v for k, v in exc.headers.items()}
        return exc.code, resp_headers, body


def run_smoke_tests(base_url: str, api_key: str | None = None) -> bool:
    """Runs end-to-end smoke tests against the specified RateFortress instance."""
    clean_url = base_url.rstrip("/")
    print("=" * 70)
    print(" RateFortress Deployment Smoke Test Harness")
    print(f" Target Endpoint: {clean_url}")
    print("=" * 70)

    checks_passed = 0
    checks_total = 0

    def check(name: str, passed: bool, detail: str = ""):
        nonlocal checks_passed, checks_total
        checks_total += 1
        symbol = "✓ PASS" if passed else "✗ FAIL"
        if passed:
            checks_passed += 1
        print(f"[{symbol}] {name} {detail}")

    t_start = time.perf_counter()

    # 1. Health Endpoint Check
    health_url = f"{clean_url}/health"
    status, _, body = make_request(health_url)
    try:
        data = json.loads(body)
        is_healthy = status == 200 and data.get("status") == "healthy"
    except Exception:
        is_healthy = False
    check("Health Check (/health)", is_healthy, f"(HTTP {status})")

    # 2. Root Metadata Check
    root_url = f"{clean_url}/"
    status, _, body = make_request(root_url)
    try:
        data = json.loads(body)
        has_metadata = status == 200 and data.get("service") == "RateFortress"
    except Exception:
        has_metadata = False
    check("Root Service Metadata (/)", has_metadata, f"(HTTP {status})")

    # 3. Prometheus Metrics Check
    metrics_url = f"{clean_url}/metrics"
    status, headers, body = make_request(metrics_url)
    is_metrics = status == 200 and ("ratefortress_requests_total" in body or "# HELP" in body)
    check("Prometheus Telemetry (/metrics)", is_metrics, f"(HTTP {status})")

    # 4. Algorithm Comparison Engine JSON Check
    compare_url = f"{clean_url}/compare?users=5&requests_per_user=10&window=5"
    status, _, body = make_request(compare_url)
    try:
        data = json.loads(body)
        has_compare = status == 200 and "scenario" in data and len(data.get("results", [])) in (5, 6)
    except Exception:
        has_compare = False
    check("Comparison Engine JSON (/compare)", has_compare, f"(HTTP {status})")

    # 5. Algorithm Comparison Engine HTML Check
    compare_html_url = f"{clean_url}/compare?format=html"
    status, headers, body = make_request(compare_html_url)
    is_html = status == 200 and "RateFortress Comparison Engine" in body and "text/html" in headers.get("content-type", "")
    check("Comparison Engine HTML (/compare?format=html)", is_html, f"(HTTP {status})")

    # 6. Rate Limiter Enforcement on /api/test
    test_endpoint = f"{clean_url}/api/test"
    req_headers: dict[str, str] = {}
    if api_key:
        req_headers["X-API-Key"] = api_key
    else:
        req_headers["X-Forwarded-For"] = f"203.0.113.{int(time.time()) % 250}"

    enforced = False
    allowed_count = 0
    blocked_count = 0

    # Rapid burst of 15 requests (nominal limit is 10 for free/anonymous tier)
    for _ in range(15):
        st, hdrs, _ = make_request(test_endpoint, headers=req_headers)
        if st == 200:
            allowed_count += 1
        elif st == 429:
            blocked_count += 1
            if "retry-after" in hdrs:
                enforced = True

    quota_respected = (allowed_count > 0 and blocked_count > 0 and enforced)
    check(
        "Rate Limit Enforcement (/api/test)",
        quota_respected,
        f"(Allowed: {allowed_count}, Blocked: {blocked_count}, 429 + Retry-After verified)",
    )

    t_elapsed = round((time.perf_counter() - t_start), 3)

    print("-" * 70)
    print(f"Results: {checks_passed}/{checks_total} checks passed in {t_elapsed}s.")
    print("=" * 70)

    return checks_passed == checks_total


def main():
    parser = argparse.ArgumentParser(description="RateFortress Live Smoke Test Harness")
    parser.add_argument(
        "--url",
        default=os.getenv("RATEFORTRESS_URL", "http://localhost:8000"),
        help="Base URL of the running RateFortress instance",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("RATEFORTRESS_API_KEY", None),
        help="Optional API key for authenticated testing",
    )
    args = parser.parse_args()

    success = run_smoke_tests(base_url=args.url, api_key=args.api_key)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
