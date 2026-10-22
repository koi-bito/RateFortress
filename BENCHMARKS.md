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

```
Outcome:
- Fixed Window Counter Allowed : 10 / 10 requests (2x Limit Spike Leak)
- Sliding Window Log Allowed   :  5 / 10 requests (Strict Rate Preserved)
```

---

## ⚡ Round 1.5: Middleware Integration & HTTP Burst Throttling (Day 31)

Tested via `loadtests/manual_load_burst.py`:
- **Target Endpoint:** `/api/test` (Configured Limit: 10 requests / 60 seconds, Token Bucket)
- **Client Identity:** Anonymous IP (`203.0.113.195`)
- **Total Requests Sent:** 30 sequential HTTP requests

### Burst Response Progression

| Request Range | Status Code | Remaining | Retry-After | Middleware Action |
| :--- | :--- | :--- | :--- | :--- |
| **#1 to #10** | **HTTP 200 OK** | 9 down to 0 | 0s (10th: 6s) | Allowed (Token consumed) |
| **#11 to #30** | **HTTP 429 Too Many Requests** | 0 | 6s | **Throttled (Quota exhausted)** |

- **Empirical Validation:** The transition from HTTP 200 to HTTP 429 occurred at **exact request #11**, verifying zero leak beyond the nominal quota of 10 requests.
- **Header Integrity:** Blocks cleanly transmitted `Retry-After: 6` indicating the precise recovery duration for the Token Bucket to accumulate at least 1 unit of capacity.
