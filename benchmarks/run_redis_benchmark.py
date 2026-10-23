"""Benchmark harness for Redis-backed rate limiting algorithms.

Compares in-memory pure Python vs Redis-backed algorithms.
"""

import os
import sys
import time
from pathlib import Path

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.algorithms.fixed_window import FixedWindowCounter
from src.algorithms.redis_fixed_window import RedisFixedWindow
from src.algorithms.redis_sliding_window_counter import RedisSlidingWindowCounter
from src.algorithms.redis_sliding_window_log import RedisSlidingWindowLog
from src.algorithms.sliding_window_counter import SlidingWindowCounter
from src.algorithms.sliding_window_log import SlidingWindowLog
from src.storage.redis_client import get_redis_client


def benchmark_algo(algo, name: str, num_requests: int = 10_000, num_users: int = 100):
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
        "throughput": throughput,
        "elapsed": elapsed,
        "allowed": allowed,
        "blocked": blocked,
    }


def main():
    os.environ["USE_FAKE_REDIS"] = "true"
    redis_client = get_redis_client(db=2)
    redis_client.flushdb()

    py_fixed = FixedWindowCounter(limit=50, window_seconds=10)
    redis_fixed = RedisFixedWindow(redis_client, limit=50, window_seconds=10)

    py_swc = SlidingWindowCounter(limit=50, window_seconds=10)
    redis_swc = RedisSlidingWindowCounter(redis_client, limit=50, window_seconds=10)

    py_swl = SlidingWindowLog(limit=50, window_seconds=10)
    redis_swl = RedisSlidingWindowLog(redis_client, limit=50, window_seconds=10)

    print("==================================================")
    print("      In-Memory vs Redis Rate Limiter Benchmarks  ")
    print("==================================================")

    benchmarks = [
        (py_fixed, "Pure Python Fixed Window"),
        (redis_fixed, "Redis Fixed Window (INCR/EXPIRE)"),
        (py_swc, "Pure Python Sliding Window Counter"),
        (redis_swc, "Redis Sliding Window Counter (Pipeline)"),
        (py_swl, "Pure Python Sliding Window Log"),
        (redis_swl, "Redis Sliding Window Log (ZSET)"),
    ]

    results = []
    for algo, name in benchmarks:
        results.append(benchmark_algo(algo, name))

    print("\n" + "=" * 60)
    print(f"{'Algorithm':<42} | {'Throughput (req/s)':<15}")
    print("-" * 60)
    for r in results:
        print(f"{r['name']:<42} | {r['throughput']:<15,.0f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
