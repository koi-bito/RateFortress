"""Automated Locust load testing harness for RateFortress (Days 46–50).

Spins up FastAPI / Uvicorn server instances under distinct storage configurations
(Synchronous Redis vs. Asynchronous Non-blocking Redis) and executes headless Locust
load tests across multiple concurrency tiers (10, 100, 500-sync, 500-async, 1000, 1500 users).
Saves CSV result matrices and generates professional latency & throughput charts.
"""

import csv
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "loadtests" / "results"
PYTHON_EXE = sys.executable
LOCUST_EXE = Path(sys.executable).parent / "locust.exe"
if not LOCUST_EXE.exists():
    LOCUST_EXE = Path(sys.executable).parent / "locust"


def start_server(backend: str, port: int = 8000) -> subprocess.Popen:
    """Spins up a Uvicorn server in a subprocess configured with target backend."""
    env = os.environ.copy()
    env["RATEFORTRESS_BACKEND"] = backend
    env["PYTHONPATH"] = str(BASE_DIR)
    env["USE_FAKE_REDIS"] = os.getenv("USE_FAKE_REDIS", "true")

    cmd = [
        str(PYTHON_EXE),
        "-m",
        "uvicorn",
        "src.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(
        cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    # Give server a moment to bind socket
    time.sleep(2.0)
    return proc


def run_locust_test(
    users: int,
    spawn_rate: int,
    run_time: str,
    csv_prefix: str,
    port: int = 8000,
) -> None:
    """Executes a headless Locust load test against the running server."""
    locustfile = BASE_DIR / "loadtests" / "locustfile.py"
    csv_path = RESULTS_DIR / csv_prefix

    cmd = [
        str(LOCUST_EXE),
        "-f",
        str(locustfile),
        "--host",
        f"http://127.0.0.1:{port}",
        "--headless",
        "-u",
        str(users),
        "-r",
        str(spawn_rate),
        "--run-time",
        run_time,
        "--exit-code-on-error",
        "0",
        f"--csv={csv_path}",
    ]

    print(
        f"--> Running Locust: users={users}, spawn_rate={spawn_rate}, time={run_time} -> {csv_prefix}..."
    )
    subprocess.run(
        cmd,
        check=False,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"    Completed {csv_prefix}.")


def parse_csv_summary(csv_prefix: str) -> dict:
    """Parses total requests, throughput, and percentiles from Locust stats CSV."""
    stats_file = RESULTS_DIR / f"{csv_prefix}_stats.csv"
    if not stats_file.exists():
        return {}

    with open(stats_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Name") == "Aggregated":
                req_count = int(row.get("Request Count", 0))
                failure_count = int(row.get("Failure Count", 0))
                fail_rate = (failure_count / req_count * 100) if req_count > 0 else 0.0
                rps = float(row.get("Requests/s", 0.0))
                med_latency = float(
                    row.get("50%", row.get("Median Response Time", 0.0))
                )
                p95_latency = float(row.get("95%", 0.0))
                p99_latency = float(row.get("99%", 0.0))
                return {
                    "scenario": csv_prefix,
                    "requests": req_count,
                    "failures": failure_count,
                    "fail_rate": fail_rate,
                    "rps": rps,
                    "p50": med_latency,
                    "p95": p95_latency,
                    "p99": p99_latency,
                }
    return {}


def generate_benchmark_chart(summaries: list[dict]):
    """Generates a professional latency and throughput comparison plot."""
    import matplotlib.pyplot as plt

    labels = [s["scenario"].replace("results_", "") for s in summaries]
    rps_values = [s["rps"] for s in summaries]
    p50_values = [s["p50"] for s in summaries]
    p95_values = [s["p95"] for s in summaries]
    p99_values = [s["p99"] for s in summaries]

    _fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Subplot 1: Throughput (RPS)
    colors = ["#2b5c8f", "#3b82f6", "#ef4444", "#10b981", "#8b5cf6", "#f59e0b"]
    ax1.bar(
        labels, rps_values, color=colors[: len(labels)], edgecolor="black", alpha=0.85
    )
    ax1.set_title(
        "Throughput Across Concurrency Levels (Req/s)", fontsize=13, fontweight="bold"
    )
    ax1.set_ylabel("Requests Per Second", fontsize=11)
    ax1.grid(axis="y", linestyle="--", alpha=0.6)
    for i, v in enumerate(rps_values):
        ax1.text(
            i,
            v + (max(rps_values) * 0.02),
            f"{int(v)}",
            ha="center",
            fontweight="bold",
            fontsize=10,
        )

    # Subplot 2: Latency Percentiles (p50, p95, p99)
    x = range(len(labels))
    width = 0.25
    ax2.bar(
        [p - width for p in x],
        p50_values,
        width=width,
        label="p50 (Median)",
        color="#3b82f6",
        alpha=0.85,
    )
    ax2.bar(x, p95_values, width=width, label="p95", color="#f59e0b", alpha=0.85)
    ax2.bar(
        [p + width for p in x],
        p99_values,
        width=width,
        label="p99",
        color="#ef4444",
        alpha=0.85,
    )
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(labels, rotation=15)
    ax2.set_title("Latency Percentiles (ms)", fontsize=13, fontweight="bold")
    ax2.set_ylabel("Response Time (ms)", fontsize=11)
    ax2.legend(loc="upper left")
    ax2.grid(axis="y", linestyle="--", alpha=0.6)

    plt.tight_layout()
    chart_path = RESULTS_DIR / "load_test_latency_comparison.png"
    plt.savefig(chart_path, dpi=300)
    plt.close()
    print(f"--> Saved chart to {chart_path}")


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []

    # 1. Day 46: 10 Users Sanity Run (in-memory)
    proc = start_server(backend="memory")
    try:
        run_locust_test(
            users=10, spawn_rate=2, run_time="10s", csv_prefix="results_10users"
        )
        s = parse_csv_summary("results_10users")
        if s:
            summaries.append(s)
    finally:
        proc.terminate()
        proc.wait()

    # 2. Day 47: 100 Users Baseline Run (in-memory)
    proc = start_server(backend="memory")
    try:
        run_locust_test(
            users=100, spawn_rate=10, run_time="15s", csv_prefix="results_100users"
        )
        s = parse_csv_summary("results_100users")
        if s:
            summaries.append(s)
    finally:
        proc.terminate()
        proc.wait()

    # 3. Day 48: 500 Users with Synchronous Redis (Event-Loop Blocking)
    proc = start_server(backend="redis_sync")
    try:
        run_locust_test(
            users=500, spawn_rate=50, run_time="15s", csv_prefix="results_500users_sync"
        )
        s = parse_csv_summary("results_500users_sync")
        if s:
            summaries.append(s)
    finally:
        proc.terminate()
        proc.wait()

    # 4. Day 48: 500 Users with Asynchronous Redis (Non-blocking Event Loop)
    proc = start_server(backend="redis_async")
    try:
        run_locust_test(
            users=500,
            spawn_rate=50,
            run_time="15s",
            csv_prefix="results_500users_async",
        )
        s = parse_csv_summary("results_500users_async")
        if s:
            summaries.append(s)
    finally:
        proc.terminate()
        proc.wait()

    # 5. Day 49: 1000 Users Scale Test (Async Redis)
    proc = start_server(backend="redis_async")
    try:
        run_locust_test(
            users=1000, spawn_rate=100, run_time="15s", csv_prefix="results_1000users"
        )
        s = parse_csv_summary("results_1000users")
        if s:
            summaries.append(s)
    finally:
        proc.terminate()
        proc.wait()

    # 6. Day 49: Stress Test / Capacity Ceiling (1500 users)
    proc = start_server(backend="redis_async")
    try:
        run_locust_test(
            users=1500, spawn_rate=250, run_time="15s", csv_prefix="results_stress"
        )
        s = parse_csv_summary("results_stress")
        if s:
            summaries.append(s)
    finally:
        proc.terminate()
        proc.wait()

    # Print summary table
    print("\n================== LOAD TEST RESULTS SUMMARY ==================")
    print(
        f"{'Scenario':<25} | {'Throughput':<12} | {'p50 (ms)':<10} | {'p95 (ms)':<10} | {'p99 (ms)':<10} | {'Fail Rate':<10}"
    )
    print("-" * 85)
    for s in summaries:
        print(
            f"{s['scenario']:<25} | {s['rps']:<10.1f} req/s | {s['p50']:<10.1f} | {s['p95']:<10.1f} | {s['p99']:<10.1f} | {s['fail_rate']:<9.1f}%"
        )
    print("===============================================================\n")

    # Generate visual chart
    generate_benchmark_chart(summaries)


if __name__ == "__main__":
    main()
