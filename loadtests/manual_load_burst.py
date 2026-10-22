"""Manual Load Burst Script (Day 31).

Fires a burst of rapid sequential requests against the RateFortress API
and tracks the exact transition from HTTP 200 OK to HTTP 429 Too Many Requests.
"""

import sys
import time
from pathlib import Path

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src.api.main import app


def run_burst_test(num_requests: int = 30, endpoint: str = "/api/test"):
    client = TestClient(app)
    headers = {"X-Forwarded-For": "203.0.113.195"}

    print("=======================================================================")
    print("           RateFortress Manual Request Burst Simulation                ")
    print(f"           Target: {endpoint} | Total Requests: {num_requests}        ")
    print("=======================================================================\n")
    print(
        f"{'Req #':<8} | {'Status Code':<15} | {'Remaining':<12} | {'Retry-After':<12} | {'Action':<15}"
    )
    print("-" * 70)

    allowed_count = 0
    blocked_count = 0
    first_blocked_at = None

    start_time = time.perf_counter()

    for i in range(1, num_requests + 1):
        resp = client.get(endpoint, headers=headers)
        status = resp.status_code
        remaining = resp.headers.get("X-RateLimit-Remaining", "-")
        retry_after = resp.headers.get("Retry-After", "-")

        if status == 200:
            allowed_count += 1
            action = "ALLOWED (✓)"
        elif status == 429:
            blocked_count += 1
            action = "THROTTLED (429)"
            if first_blocked_at is None:
                first_blocked_at = i
        else:
            action = f"OTHER ({status})"

        print(
            f"#{i:<7} | HTTP {status:<10} | {remaining:<12} | {retry_after:<12} | {action:<15}"
        )

    elapsed = time.perf_counter() - start_time

    print("\n" + "=" * 70)
    print("Results Summary:")
    print(f"  Total Requests Fired  : {num_requests}")
    print(f"  Allowed (HTTP 200)    : {allowed_count}")
    print(f"  Blocked (HTTP 429)    : {blocked_count}")
    print(f"  First 429 Triggered At: Request #{first_blocked_at}")
    print(
        f"  Total Burst Duration  : {elapsed:.4f}s ({num_requests/elapsed:,.0f} req/s)"
    )
    print("=======================================================================")


if __name__ == "__main__":
    run_burst_test()
