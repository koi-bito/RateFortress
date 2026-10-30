"""Benchmark harness for Redis-backed rate limiting algorithms.

Compares in-memory pure Python vs distributed Redis-backed algorithms across all 5 implementations.
"""

import os
import sys
import time
from pathlib import Path

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.algorithms.fixed_window import FixedWindowCounter
from src.algorithms.gcra import GCRA
from src.algorithms.leaky_bucket import LeakyBucket
from src.algorithms.redis_fixed_window import RedisFixedWindow
from src.algorithms.redis_gcra import RedisGCRA
from src.algorithms.redis_leaky_bucket import RedisLeakyBucket
from src.algorithms.redis_sliding_window_counter import RedisSlidingWindowCounter
from src.algorithms.redis_sliding_window_log import RedisSlidingWindowLog
from src.algorithms.redis_token_bucket import RedisTokenBucket
from src.algorithms.sliding_window_counter import SlidingWindowCounter
from src.algorithms.sliding_window_log import SlidingWindowLog
from src.algorithms.token_bucket import TokenBucket
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

    # Fixed Window
    py_fixed = FixedWindowCounter(limit=50, window_seconds=10)
    redis_fixed = RedisFixedWindow(redis_client, limit=50, window_seconds=10)

    # Sliding Window Counter
    py_swc = SlidingWindowCounter(limit=50, window_seconds=10)
    redis_swc = RedisSlidingWindowCounter(redis_client, limit=50, window_seconds=10)

    # Sliding Window Log
    py_swl = SlidingWindowLog(limit=50, window_seconds=10)
    redis_swl = RedisSlidingWindowLog(redis_client, limit=50, window_seconds=10)

    # Token Bucket
    py_tb = TokenBucket(capacity=50, refill_rate_per_sec=5.0)
    redis_tb = RedisTokenBucket(redis_client, capacity=50, refill_rate_per_sec=5.0)

    # Leaky Bucket
    py_lb = LeakyBucket(capacity=50, leak_rate_per_sec=5.0)
    redis_lb = RedisLeakyBucket(redis_client, capacity=50, leak_rate_per_sec=5.0)

    # GCRA (Cell Rate)
    py_gcra = GCRA(limit=50, period=10.0)
    redis_gcra = RedisGCRA(redis_client, limit=50, period=10.0)

    print("==================================================")
    print("      In-Memory vs Redis Rate Limiter Benchmarks  ")
    print("==================================================")

    benchmarks = [
        (py_fixed, "Pure Python Fixed Window"),
        (redis_fixed, "Redis Fixed Window (INCR/EXPIRE)"),
        (py_swc, "Pure Python Sliding Window Counter"),
        (redis_swc, "Redis Sliding Window Counter (Atomic Lua)"),
        (py_swl, "Pure Python Sliding Window Log"),
        (redis_swl, "Redis Sliding Window Log (Atomic Lua)"),
        (py_tb, "Pure Python Token Bucket"),
        (redis_tb, "Redis Token Bucket (Atomic Lua)"),
        (py_lb, "Pure Python Leaky Bucket"),
        (redis_lb, "Redis Leaky Bucket (Atomic Lua)"),
        (py_gcra, "Pure Python GCRA (Cell Rate)"),
        (redis_gcra, "Redis GCRA (Atomic Lua)"),
    ]

    results = []
    for algo, name in benchmarks:
        results.append(benchmark_algo(algo, name))

    print("\n" + "=" * 65)
    print(f"{'Algorithm':<45} | {'Throughput (req/s)':<15}")
    print("-" * 65)
    for r in results:
        print(f"{r['name']:<45} | {r['throughput']:<15,.0f}")
    print("=" * 65)


if __name__ == "__main__":
    main()
