# RateFortress — Benchmark Results & Analysis

This document tracks empirical throughput, latency, and memory characteristics across all rate limiting algorithms and storage backends.

---

## 💻 Test Environment

- **OS:** Windows / Linux
- **Python Version:** 3.13+
- **Harness:** `benchmarks/run_benchmark.py` (Default: 10,000 requests, 100 concurrent simulated users)

---

## 📊 Round 1: In-Memory Pure Python Implementations (Upcoming - Weeks 2-3)

| Algorithm | Throughput (req/s) | Allowed | Blocked | Elapsed (s) | Memory / User | Burst Tolerance | Boundary Leak? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Fixed Window Counter** | *Pending (Day 12)* | - | - | - | O(1) (~few bytes) | None | Yes (up to 2x) |
| **Sliding Window Log** | *Pending (Day 14)* | - | - | - | O(N) (timestamps) | None | No (Exact) |
| **Sliding Window Counter** | *Pending (Day 16)* | - | - | - | O(1) (~few bytes) | None | No (Approximation) |
| **Token Bucket** | *Pending (Day 17)* | - | - | - | O(1) (~few bytes) | Configurable burst | No |
| **Leaky Bucket** | *Pending (Day 18)* | - | - | - | O(Queue size) | Strict queue outflow | No |

---

## 📈 Round 2: Distributed Redis & Lua Scripts (Upcoming - Weeks 7-8)

*(To be benchmarked under simulated network latency & concurrency)*
