"""Reusable benchmark harness for rate limiting algorithms.

Each algorithm must implement: is_allowed(user_id: str) -> bool
"""

import time


def benchmark_algorithm(algo, name, num_requests=10_000, num_users=100):
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
    print(f"Total requests: {num_requests}")
    print(f"Allowed: {allowed} | Blocked: {blocked}")
    print(f"Time: {elapsed:.4f}s | Throughput: {throughput:.0f} req/s")
    return {"name": name, "allowed": allowed, "blocked": blocked, "elapsed": elapsed}


if __name__ == "__main__":
    print("Benchmark harness ready. Algorithms will be plugged in starting Week 2.")
