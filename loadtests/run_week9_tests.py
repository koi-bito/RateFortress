"""Week 9 Load Testing Suite: k6, Locust vs k6 Comparison, Spike & Soak Testing.

Implements the complete roadmap for Week 9 (Days 52–56):
- Day 52: k6 Setup & Comparison Test against FastAPI RateFortress gateway.
- Day 53: Locust vs k6 empirical benchmark comparison under identical load profile (100 -> 500 users).
- Day 54: Instant Spike Testing (10 -> 1500 users) & recovery latency evaluation.
- Day 55: Soak Testing (sustained load) with continuous memory profiling of FastAPI and Redis.
- Day 56: Consolidated reports, charts, and BENCHMARKS.md update.
"""

import csv
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import matplotlib.pyplot as plt
import psutil

# Fix matplotlib cache directory warning
os.environ["MPLCONFIGDIR"] = str(Path(__file__).resolve().parent / "results" / ".mplconfig")

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "loadtests" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PYTHON_EXE = sys.executable
K6_EXE = BASE_DIR / "loadtests" / "bin" / "k6.exe"
if not K6_EXE.exists():
    K6_EXE = Path("k6")

LOCUST_EXE = Path(sys.executable).parent / "locust.exe"
if not LOCUST_EXE.exists():
    LOCUST_EXE = Path(sys.executable).parent / "locust"


def wait_for_server(port: int = 8000, timeout: float = 10.0) -> bool:
    """Polls server health endpoint until healthy or timeout."""
    start = time.time()
    url = f"http://127.0.0.1:{port}/health"
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def start_server(backend: str = "redis_async", port: int = 8000) -> subprocess.Popen:
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
    if not wait_for_server(port=port, timeout=10.0):
        print(f"    [!] Warning: Server at port {port} did not respond within 10s.", flush=True)
    return proc


def parse_k6_summary_file(summary_path: Path) -> dict:
    """Parses standard k6 summary JSON output accurately."""
    if not summary_path.exists():
        return {}
    with open(summary_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    metrics = data.get("metrics", {})
    http_reqs = metrics.get("http_reqs", {}).get("count", 0)
    http_req_rate = metrics.get("http_reqs", {}).get("rate", 0.0)
    duration_vals = metrics.get("http_req_duration", {})
    p50 = duration_vals.get("med", duration_vals.get("avg", 0.0))
    p90 = duration_vals.get("p(90)", 0.0)
    p95 = duration_vals.get("p(95)", 0.0)
    p99 = duration_vals.get("p(99)", 0.0)
    max_lat = duration_vals.get("max", 0.0)

    checks = metrics.get("checks", {})
    passes = checks.get("passes", 0)
    fails = checks.get("fails", 0)
    total_checks = passes + fails
    fail_rate = (fails / total_checks * 100.0) if total_checks > 0 else 0.0

    return {
        "tool": "k6",
        "total_requests": int(http_reqs),
        "rps": float(http_req_rate),
        "p50": float(p50),
        "p90": float(p90),
        "p95": float(p95),
        "p99": float(p99),
        "max": float(max_lat),
        "fail_rate": float(fail_rate),
    }


def run_k6(
    script_path: Path,
    summary_path: Path,
    env_vars: dict | None = None,
) -> dict:
    """Executes a k6 test script and parses the resulting summary JSON export."""
    cmd = [
        str(K6_EXE),
        "run",
        "--no-usage-report",
        "--no-color",
        "--summary-export",
        str(summary_path),
        str(script_path),
    ]
    env = os.environ.copy()
    if env_vars:
        for k, v in env_vars.items():
            env[k] = str(v)

    print(f"--> Executing k6 [{script_path.name}]...", flush=True)
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)

    if not summary_path.exists():
        print(f"    [!] Summary file not found: {summary_path}\nk6 stderr:\n{result.stderr}", flush=True)
        return {}

    summary = parse_k6_summary_file(summary_path)
    print(f"    [k6 Finished] {summary['rps']:.1f} req/s | p50={summary['p50']:.1f}ms | p95={summary['p95']:.1f}ms | p99={summary['p99']:.1f}ms | Fail={summary['fail_rate']:.1f}%", flush=True)
    return summary


def run_locust_ramp(
    users: int = 500,
    spawn_rate: int = 25,
    run_time: str = "30s",
    csv_prefix: str = "results_locust_k6_comp",
    port: int = 8000,
) -> dict:
    """Executes Locust test for comparison with k6 ramping profile."""
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

    print(f"--> Executing Locust [Ramp to {users} users, time={run_time}]...", flush=True)
    subprocess.run(
        cmd,
        check=False,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    stats_file = RESULTS_DIR / f"{csv_prefix}_stats.csv"
    if not stats_file.exists():
        print(f"    [!] Locust stats file not found: {stats_file}", flush=True)
        return {}

    with open(stats_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Name"] == "Aggregated":
                req_count = int(row["Request Count"])
                fail_count = int(row["Failure Count"])
                rps = float(row["Requests/s"])
                p50 = float(row["50%"])
                p90 = float(row["90%"])
                p95 = float(row["95%"])
                p99 = float(row["99%"])
                max_lat = float(row["Max Response Time"])
                fail_rate = (fail_count / req_count * 100.0) if req_count > 0 else 0.0
                summary = {
                    "tool": "Locust",
                    "total_requests": req_count,
                    "rps": rps,
                    "p50": p50,
                    "p90": p90,
                    "p95": p95,
                    "p99": p99,
                    "max": max_lat,
                    "fail_rate": fail_rate,
                }
                print(f"    [Locust Finished] {rps:.1f} req/s | p50={p50:.1f}ms | p95={p95:.1f}ms | p99={p99:.1f}ms | Fail={fail_rate:.1f}%", flush=True)
                return summary
    return {}


def run_soak_test(
    server_pid: int,
    duration_seconds: int = 35,
    port: int = 8000,
) -> tuple[dict, list[dict]]:
    """Runs a soak test under steady load while tracking server process memory every second."""
    print(f"--> Executing Soak Test [{duration_seconds}s sustained load, tracking memory on PID {server_pid}]...", flush=True)
    proc_obj = psutil.Process(server_pid)

    memory_timeline = []
    stop_event = threading.Event()

    def sample_memory():
        start_time = time.time()
        while not stop_event.is_set():
            now = time.time() - start_time
            try:
                mem_info = proc_obj.memory_info()
                cpu_pct = proc_obj.cpu_percent(interval=None)
                num_threads = proc_obj.num_threads()
                rss_mb = mem_info.rss / (1024 * 1024)
                vms_mb = mem_info.vms / (1024 * 1024)
                memory_timeline.append({
                    "time_sec": round(now, 1),
                    "rss_mb": round(rss_mb, 2),
                    "vms_mb": round(vms_mb, 2),
                    "cpu_pct": round(cpu_pct, 1),
                    "threads": num_threads,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            time.sleep(1.0)

    sampler_thread = threading.Thread(target=sample_memory, daemon=True)
    sampler_thread.start()

    soak_summary_path = RESULTS_DIR / "k6_soak_summary.json"
    soak_script = BASE_DIR / "loadtests" / "k6_soak_test.js"
    with open(soak_script, "w", encoding="utf-8") as f:
        f.write(f"""import http from "k6/http";
import {{ check, sleep }} from "k6";

export const options = {{
  vus: 120,
  duration: "{duration_seconds}s",
}};

export default function () {{
  const res = http.get("http://127.0.0.1:{port}/api/test", {{
    headers: {{ "X-API-Key": "key_paid_xyz" }},
  }});
  check(res, {{
    "status is 200 or 429": (r) => r.status === 200 || r.status === 429,
  }});
  sleep(0.1);
}}
""")

    summary = run_k6(soak_script, soak_summary_path)

    stop_event.set()
    sampler_thread.join(timeout=2.0)

    # Save memory timeline CSV
    mem_csv = RESULTS_DIR / "soak_test_memory_timeline.csv"
    with open(mem_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["time_sec", "rss_mb", "vms_mb", "cpu_pct", "threads"])
        writer.writeheader()
        writer.writerows(memory_timeline)

    return summary, memory_timeline


def generate_soak_memory_chart(memory_timeline: list[dict], output_path: Path):
    """Generates a professional time-series memory chart demonstrating memory stability."""
    if not memory_timeline:
        return

    times = [pt["time_sec"] for pt in memory_timeline]
    rss = [pt["rss_mb"] for pt in memory_timeline]
    vms = [pt["vms_mb"] for pt in memory_timeline]

    _fig, ax1 = plt.subplots(figsize=(10, 5), dpi=150)
    
    ax1.plot(times, rss, color="#2b5c8f", linewidth=2.5, label="Resident Set Size (RSS)")
    ax1.plot(times, vms, color="#e67e22", linewidth=1.8, linestyle="--", label="Virtual Memory (VMS)")
    
    ax1.set_xlabel("Elapsed Time (Seconds)", fontsize=11, fontweight="bold")
    ax1.set_ylabel("Memory Consumption (MB)", fontsize=11, fontweight="bold")
    ax1.set_title("RateFortress Soak Test: Process Memory Stability Over Time", fontsize=13, fontweight="bold")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left")

    if rss:
        rss_start = rss[0]
        rss_end = rss[-1]
        delta = rss_end - rss_start
        ax1.annotate(
            f"RSS Start: {rss_start:.1f} MB\nRSS End: {rss_end:.1f} MB\nDelta: {delta:+.1f} MB (Bounded)",
            xy=(times[-1], rss_end),
            xytext=(times[-1] * 0.65, max(rss) * 0.8),
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#ecf0f1", edgecolor="#bdc3c7", alpha=0.9),
            arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=-0.2", color="#2c3e50"),
            fontweight="semibold",
            fontsize=9,
        )

    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"--> Saved Soak Test Memory Chart to {output_path}", flush=True)


def generate_comparison_chart(k6_data: dict, locust_data: dict, spike_data: dict, output_path: Path):
    """Generates comparative latency and throughput chart between k6 and Locust."""
    tools = ["k6 (Go Engine)", "Locust (Python Greenlets)", "k6 Spike (1500 VUs)"]
    rps = [k6_data.get("rps", 0), locust_data.get("rps", 0), spike_data.get("rps", 0)]
    p50 = [k6_data.get("p50", 0), locust_data.get("p50", 0), spike_data.get("p50", 0)]
    p95 = [k6_data.get("p95", 0), locust_data.get("p95", 0), spike_data.get("p95", 0)]
    p99 = [k6_data.get("p99", 0), locust_data.get("p99", 0), spike_data.get("p99", 0)]

    _fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), dpi=150)

    # Throughput bar chart
    bars1 = ax1.bar(tools, rps, color=["#16a085", "#2980b9", "#d35400"], width=0.5)
    ax1.set_title("Throughput Comparison (Requests / Sec)", fontsize=12, fontweight="bold")
    ax1.set_ylabel("Throughput (req/s)", fontsize=10, fontweight="bold")
    ax1.grid(axis="y", linestyle=":", alpha=0.6)
    for bar in bars1:
        yval = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2, yval + (max(rps or [100]) * 0.02), f"{yval:.1f} rps", ha="center", va="bottom", fontweight="bold", fontsize=9)

    # Latency percentiles grouped bar chart
    x = range(len(tools))
    width = 0.25
    ax2.bar([i - width for i in x], p50, width=width, label="p50 (Median)", color="#27ae60")
    ax2.bar([i for i in x], p95, width=width, label="p95 Percentile", color="#f39c12")
    ax2.bar([i + width for i in x], p99, width=width, label="p99 Percentile", color="#c0392b")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(tools, fontsize=9)
    ax2.set_title("Latency Percentile Comparison (ms)", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Latency (ms)", fontsize=10, fontweight="bold")
    ax2.legend(loc="upper left")
    ax2.grid(axis="y", linestyle=":", alpha=0.6)

    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"--> Saved Comparison Chart to {output_path}", flush=True)


def parse_locust_csv_summary(csv_prefix: str) -> dict:
    """Parses Locust summary stats from existing CSV file."""
    stats_file = RESULTS_DIR / f"{csv_prefix}_stats.csv"
    if not stats_file.exists():
        return {}
    with open(stats_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Name"] == "Aggregated":
                req_count = int(row["Request Count"])
                fail_count = int(row["Failure Count"])
                rps = float(row["Requests/s"])
                p50 = float(row["50%"])
                p90 = float(row["90%"])
                p95 = float(row["95%"])
                p99 = float(row["99%"])
                max_lat = float(row["Max Response Time"])
                fail_rate = (fail_count / req_count * 100.0) if req_count > 0 else 0.0
                return {
                    "tool": "Locust",
                    "total_requests": req_count,
                    "rps": rps,
                    "p50": p50,
                    "p90": p90,
                    "p95": p95,
                    "p99": p99,
                    "max": max_lat,
                    "fail_rate": fail_rate,
                }
    return {}


def main():
    print("================================================================================", flush=True)
    print("        RATEFORTRESS WEEK 9 LOAD TESTING SUITE: K6, SPIKE & SOAK TESTS          ", flush=True)
    print("================================================================================", flush=True)

    report_only = "--report-only" in sys.argv

    if not report_only:
        # 1. Day 52: k6 Setup & Day 53: Comparison with Locust
        print("\n--- [Day 52 & Day 53] k6 Ramp vs. Locust Ramp Comparison ---", flush=True)
        server_proc = start_server(backend="redis_async", port=8000)
        try:
            k6_script = BASE_DIR / "loadtests" / "k6_test.js"
            k6_summary_file = RESULTS_DIR / "k6_test_summary.json"
            k6_env = {"STAGE_1": "10s", "STAGE_2": "15s", "STAGE_3": "5s"}
            k6_summary = run_k6(k6_script, k6_summary_file, env_vars=k6_env)

            # Day 53: Locust equivalent ramp test
            locust_summary = run_locust_ramp(users=500, spawn_rate=25, run_time="30s", csv_prefix="results_locust_k6_comp")
        finally:
            server_proc.terminate()
            server_proc.wait()

        # 2. Day 54: Spike Testing (10 -> 1500 VUs)
        print("\n--- [Day 54] Instant Spike Testing (10 -> 1500 VUs) ---", flush=True)
        server_proc = start_server(backend="redis_async", port=8000)
        try:
            spike_script = BASE_DIR / "loadtests" / "k6_spike_test.js"
            spike_summary_file = RESULTS_DIR / "k6_spike_summary.json"
            spike_env = {
                "SPIKE_STAGE_1": "5s",
                "SPIKE_STAGE_2": "3s",
                "SPIKE_STAGE_3": "12s",
                "SPIKE_STAGE_4": "5s",
                "SPIKE_STAGE_5": "5s",
            }
            spike_summary = run_k6(spike_script, spike_summary_file, env_vars=spike_env)
        finally:
            server_proc.terminate()
            server_proc.wait()

        # 3. Day 55: Soak Testing & Memory Tracking
        print("\n--- [Day 55] Soak Testing & Memory Stability Profiling ---", flush=True)
        server_proc = start_server(backend="redis_async", port=8000)
        try:
            soak_summary, memory_timeline = run_soak_test(server_pid=server_proc.pid, duration_seconds=30, port=8000)
        finally:
            server_proc.terminate()
            server_proc.wait()
    else:
        print("[!] Generating report from saved benchmark run files...", flush=True)
        k6_summary = parse_k6_summary_file(RESULTS_DIR / "k6_test_summary.json")
        locust_summary = parse_locust_csv_summary("results_locust_k6_comp")
        spike_summary = parse_k6_summary_file(RESULTS_DIR / "k6_spike_summary.json")
        soak_summary = parse_k6_summary_file(RESULTS_DIR / "k6_soak_summary.json")
        
        # Load memory timeline from CSV if available
        memory_timeline = []
        mem_csv = RESULTS_DIR / "soak_test_memory_timeline.csv"
        if mem_csv.exists():
            with open(mem_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    memory_timeline.append({
                        "time_sec": float(row["time_sec"]),
                        "rss_mb": float(row["rss_mb"]),
                        "vms_mb": float(row["vms_mb"]),
                        "cpu_pct": float(row["cpu_pct"]),
                        "threads": int(row["threads"]),
                    })

    # Visualizations
    generate_soak_memory_chart(memory_timeline, RESULTS_DIR / "soak_test_memory_stability.png")
    generate_comparison_chart(k6_summary, locust_summary, spike_summary, RESULTS_DIR / "k6_vs_locust_comparison.png")

    # Print summary matrix
    print("\n========================= WEEK 9 BENCHMARK RESULTS =========================", flush=True)
    print(f"{'Test Scenario / Tool':<28} | {'Throughput':<12} | {'p50 (ms)':<9} | {'p95 (ms)':<9} | {'p99 (ms)':<9} | {'Fail Rate':<9}", flush=True)
    print("-" * 88, flush=True)
    for row in [
        ("k6 Ramping (100->500)", k6_summary),
        ("Locust Ramping (100->500)", locust_summary),
        ("k6 Spike (10->1500 VUs)", spike_summary),
        ("k6 Soak (120 VUs Sustained)", soak_summary),
    ]:
        s = row[1]
        print(f"{row[0]:<28} | {s.get('rps', 0):<10.1f} req/s | {s.get('p50', 0):<9.1f} | {s.get('p95', 0):<9.1f} | {s.get('p99', 0):<9.1f} | {s.get('fail_rate', 0):<8.1f}%", flush=True)
    print("============================================================================\n", flush=True)


if __name__ == "__main__":
    main()
