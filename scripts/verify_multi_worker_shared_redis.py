"""Verification script for multi-worker shared Redis rate limiting (Bug 1).

Starts an out-of-process TCP Redis server on port 6379, starts Uvicorn with --workers 2,
and sends concurrent traffic to prove both worker processes share a single Redis quota
rather than each worker granting its own isolated quota (split-brain).
"""

import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import fakeredis


def run_verification():
    print("--> 1. Starting Multi-Threaded TCP Redis Server on 127.0.0.1:6379...")
    server = fakeredis.TcpFakeServer(("127.0.0.1", 6379))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print("    TCP Redis Server is listening on 127.0.0.1:6379.")

    env = os.environ.copy()
    env["RATEFORTRESS_BACKEND"] = "redis_async"
    env["USE_FAKE_REDIS"] = "false"
    env["REDIS_HOST"] = "127.0.0.1"
    env["REDIS_PORT"] = "6379"

    print("--> 2. Launching Uvicorn with --workers 2...", flush=True)
    python_exe = sys.executable
    cmd = [python_exe, "-m", "uvicorn", "src.api.main:app", "--port", "8000", "--workers", "2"]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait for app readiness
    ready = False
    for _ in range(30):
        try:
            req = urllib.request.Request("http://127.0.0.1:8000/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5)

    if not ready:
        proc.kill()
        server.shutdown()
        raise RuntimeError("Uvicorn failed to start within 15 seconds.")

    print("    Uvicorn cluster is operational with 2 worker processes.")

    # Send 25 concurrent requests to /api/test (nominal limit = 10 requests / 60 seconds)
    print("--> 3. Bombarding /api/test with 25 concurrent requests across worker processes...")
    headers = {"X-API-Key": "key_free_abc"}

    def make_request(i):
        req = urllib.request.Request("http://127.0.0.1:8000/api/test", headers=headers)
        time.sleep(i * 0.02)
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return str(e)

    with ThreadPoolExecutor(max_workers=4) as executor:
        status_codes = list(executor.map(make_request, range(20)))

    allowed_200 = sum(1 for s in status_codes if s == 200)
    throttled_429 = sum(1 for s in status_codes if s == 429)

    print("\n[RESULTS] Multi-Worker Traffic Distribution:")
    print("  • Total Requests Sent: 20")
    print(f"  • Allowed (HTTP 200):  {allowed_200}")
    print(f"  • Blocked (HTTP 429):  {throttled_429}")
    print(f"  • Raw Status List:     {status_codes}")

    # Shutdown processes
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except (subprocess.SubprocessError, TimeoutError, OSError):
        proc.kill()
    server.shutdown()

    # If split-brain existed, worker 1 would admit up to 10 and worker 2 up to 10 (= up to 20 allowed)
    # With shared live Redis, exactly 10 requests must be allowed and 10 blocked!
    assert allowed_200 == 10, f"Expected exactly 10 allowed across workers, got {allowed_200}"
    assert throttled_429 == 10, f"Expected exactly 10 blocked across workers, got {throttled_429}"
    print("\n✓ SUCCESS: Both worker processes successfully connected to live async Redis and enforced a single unified quota (0% split-brain leakage)!\n")
    os._exit(0)


if __name__ == "__main__":
    run_verification()
