"""Reusable benchmark harness for rate limiting algorithms.

Each algorithm must implement: is_allowed(user_id: str) -> bool
"""

import sys
import time
from pathlib import Path

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.algorithms.fixed_window import FixedWindowCounter
from src.algorithms.gcra import GCRA
from src.algorithms.leaky_bucket import LeakyBucket
from src.algorithms.sliding_window_counter import SlidingWindowCounter
from src.algorithms.sliding_window_log import SlidingWindowLog
from src.algorithms.token_bucket import TokenBucket


def benchmark_algorithm(
    algo, name: str, num_requests: int = 10_000, num_users: int = 100
):
    start = time.perf_counter()
    allowed, blocked = 0, 0

    for i in range(num_requests):
        user_id = f"user_{i % num_users}"
        if algo.is_allowed(user_id):
            allowed += 1
        else:
            blocked += 1

    elapsed = time.perf_counter() - start
    throughput = num_requests / elapsed if elapsed > 0 else 0
    print(f"\n--- {name} ---")
    print(f"Total requests: {num_requests:,} | Users: {num_users}")
    print(f"Allowed: {allowed:,} | Blocked: {blocked:,}")
    print(f"Time: {elapsed:.4f}s | Throughput: {throughput:,.0f} req/s")
    return {
        "name": name,
        "num_requests": num_requests,
        "allowed": allowed,
        "blocked": blocked,
        "elapsed": elapsed,
        "throughput": throughput,
    }


def run_all_benchmarks():
    print("==================================================")
    print("      RateFortress 6-Algorithm Benchmark Suite    ")
    print("==================================================")

    # Standard benchmark profile: 10,000 requests across 100 users, limit=50 per 10s
    algorithms = [
        (FixedWindowCounter(limit=50, window_seconds=10), "Fixed Window Counter"),
        (SlidingWindowLog(limit=50, window_seconds=10), "Sliding Window Log"),
        (SlidingWindowCounter(limit=50, window_seconds=10), "Sliding Window Counter"),
        (TokenBucket(capacity=50, refill_rate_per_sec=5.0), "Token Bucket"),
        (LeakyBucket(capacity=50, leak_rate_per_sec=5.0), "Leaky Bucket"),
        (GCRA(limit=50, period=10.0), "GCRA (Cell Rate)"),
    ]

    results = []
    for algo, name in algorithms:
        res = benchmark_algorithm(algo, name, num_requests=10_000, num_users=100)
        results.append(res)

    print("\n" + "=" * 55)
    print(f"{'Algorithm':<25} | {'Throughput (req/s)':<18} | {'Elapsed (s)':<10}")
    print("-" * 55)
    for r in results:
        print(f"{r['name']:<25} | {r['throughput']:<18,.0f} | {r['elapsed']:<10.4f}")
    print("=" * 55)
    return results


if __name__ == "__main__":
    run_all_benchmarks()
