# RateFortress — Benchmark Results & Analysis

This document tracks empirical throughput, latency, and memory characteristics across all rate limiting algorithms and storage backends.

---

## 💻 Test Environment

- **OS:** Windows (x86_64)
- **Python Version:** 3.13.13
- **Harness:** `benchmarks/run_benchmark.py` (10,000 requests, 100 simulated concurrent users, limit = 50 reqs / 10s)

---

## 📊 Round 1: In-Memory Pure Python Implementations

| Algorithm | Throughput (req/s) | Allowed | Blocked | Elapsed (s) | Memory / User | Burst Tolerance | Boundary Leak? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Fixed Window Counter** | **2,819,761 req/s** | 5,000 | 5,000 | 0.0035s | $O(1)$ (~48 bytes) | None | **Yes (up to 2x limit)** |
| **Sliding Window Log** | **3,471,620 req/s** | 5,000 | 5,000 | 0.0029s | $O(N)$ (timestamps) | None | **No (Strict Guarantee)** |
| **Sliding Window Counter** | **2,115,551 req/s** | 5,000 | 5,000 | 0.0047s | $O(1)$ (~64 bytes) | None | **No (Smooth Approximation)** |
| **Token Bucket** | **2,066,073 req/s** | 5,000 | 5,000 | 0.0048s | $O(1)$ (~48 bytes) | Configurable burst | **No** |
| **Leaky Bucket** | **2,580,845 req/s** | 5,000 | 5,000 | 0.0039s | $O(\text{Queue size})$ | Strict queue outflow | **No** |

---

## 🔬 Empirical Tradeoff Evidence: The Window Boundary Problem (Day 15)

Tested via `benchmarks/compare_window_boundary.py`:
- **Scenario:** Limit = 5 requests per 10-second window.
- **Traffic Pattern:** 5 requests sent at the tail of window 1 ($t=8.0$ to $9.9$), followed immediately by 5 requests at the start of window 2 ($t=10.1$ to $10.5$).
- **Rolling Window Impact:** In the 2.5-second span ($t=8.0$ to $10.5$), 10 total requests arrived.

### Side-by-Side Results

```
Request  | Timestamp  | Fixed Window Counter | Sliding Window Log
-----------------------------------------------------------------
#1       | t=8.0s     | ALLOWED (✓)          | ALLOWED (✓)
#2       | t=8.5s     | ALLOWED (✓)          | ALLOWED (✓)
#3       | t=9.0s     | ALLOWED (✓)          | ALLOWED (✓)
#4       | t=9.5s     | ALLOWED (✓)          | ALLOWED (✓)
#5       | t=9.9s     | ALLOWED (✓)          | ALLOWED (✓)
#6       | t=10.1s    | ALLOWED (✓) [BURST!] | BLOCKED (✗)
#7       | t=10.2s    | ALLOWED (✓) [BURST!] | BLOCKED (✗)
#8       | t=10.3s    | ALLOWED (✓) [BURST!] | BLOCKED (✗)
#9       | t=10.4s    | ALLOWED (✓) [BURST!] | BLOCKED (✗)
#10      | t=10.5s    | ALLOWED (✓) [BURST!] | BLOCKED (✗)
-----------------------------------------------------------------
Outcome:
- Fixed Window Counter Allowed : 10 / 10 requests (2x Limit Spike Leak)
- Sliding Window Log Allowed   :  5 / 10 requests (Strict Rate Preserved)
```

### Analysis & Takeaway
1. **Fixed Window Counter** suffers from boundary vulnerability: traffic clustered around window boundaries resets the quota early, potentially permitting up to **$2 \times \text{limit}$** in a rolling duration equal to window length. However, its memory complexity is strictly $O(1)$ per user.
2. **Sliding Window Log** completely eliminates boundary spikes by inspecting the continuous rolling interval $[t - \text{window}, t]$. However, storing individual 64-bit float timestamps in a `deque` requires $O(N)$ memory, which becomes prohibitive under high request limits ($100,000\text{ reqs/min} \approx 800\text{ KB/user}$).
