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

---

## 🌐 Round 2: Distributed Redis-Backed Implementations vs. In-Memory (Days 35–37)

Tested via `benchmarks/run_redis_benchmark.py`:
- **Workload:** 10,000 requests, 100 simulated clients, limit = 50 reqs / 10s.
- **Core Tradeoff Tested:** Process-local in-memory execution speed vs. Distributed cluster-wide cross-instance synchronization.

| Algorithm Implementation | Storage Backend | Throughput (req/s) | Elapsed Time (s) | Cross-Instance Safe? | Atomicity Model |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Fixed Window Counter** | In-Memory (`defaultdict`) | **3,269,577 req/s** | 0.0031s | ❌ No (Isolated per process) | Process memory |
| **Fixed Window Counter** | Redis (`INCR` + `EXPIRE`) | **43,875 req/s** | 0.2279s | ✅ **Yes (Shared state)** | Redis Atomic `INCR` |
| **Sliding Window Counter** | In-Memory (`defaultdict`) | **2,083,160 req/s** | 0.0048s | ❌ No (Isolated per process) | Process memory |
| **Sliding Window Counter** | Redis (`Pipeline GET` + `INCR`) | **13,926 req/s** | 0.7181s | ✅ **Yes (Shared state)** | Redis Pipeline + App Math |
| **Sliding Window Log** | In-Memory (`deque`) | **3,126,857 req/s** | 0.0032s | ❌ No (Isolated per process) | Process memory |
| **Sliding Window Log** | Redis Sorted Set (`ZSET`) | **9,727 req/s** | 1.0281s | ✅ **Yes (Shared state)** | `ZREMRANGEBYSCORE` + `ZCARD` + `ZADD` |

### Key Architectural Takeaways:
1. **Network & Serialization Overhead:** Moving rate limiting state into an external key-value store incurs a throughput reduction from millions of req/s to 10k–44k req/s per single client thread. However, 10k–44k req/s is orders of magnitude higher than typical single-server HTTP throughput (~2,000 req/s for Python ASGI frameworks).
2. **Global Correctness over Raw Speed:** In-memory rate limiting completely fails when horizontal scaling adds 10 backend pods behind an AWS ALB (allowing an attacker 10x their allowed quota by round-robining across nodes). Distributed Redis state guarantees that request #1 on Pod A immediately restricts request #2 on Pod B.

---

## 🔒 Round 3: Redis Backend II — Atomic Lua Scripting & Concurrency (Days 40–45)

Tested via `benchmarks/run_redis_benchmark.py` and `tests/test_redis_concurrency.py`:
- **Workload:** 10,000 requests, 100 simulated clients, limit = 50 reqs / 10s.
- **Concurrency Test:** 50 simultaneous worker threads firing requests for the exact same user against limit = 10.

| Algorithm Implementation | Storage Backend | Atomicity Primitive | Throughput (req/s) | 50-Thread Concurrent Stress (Limit=10) | Over-Admission Leak? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Fixed Window Counter** | Redis (`INCR` + `EXPIRE`) | Redis Atomic `INCR` | **37,877 req/s** | 10 Allowed / 40 Blocked | **Zero (0%)** |
| **Sliding Window Counter** | Redis (Pipeline `GET` + `INCR`) | Pipeline + App Math | **12,955 req/s** | N/A (Statistical bound) | Boundary smoothed |
| **Sliding Window Log (Lua)** | Redis Sorted Set (`ZSET`) | **Atomic Lua Script** | **5,292 req/s** | 10 Allowed / 40 Blocked | **Zero (0%)** |
| **Token Bucket (Lua)** | Redis Hash (`HMGET`/`HMSET`) | **Atomic Lua Script** | **6,266 req/s** | 10 Allowed / 40 Blocked | **Zero (0%)** |
| **Leaky Bucket (Lua)** | Redis Hash (`HMGET`/`HMSET`) | **Atomic Lua Script** | **5,919 req/s** | 10 Allowed / 40 Blocked | **Zero (0%)** |

### Concurrency Deep-Dive: Why Lua Scripts Are Mandatory

#### 1. The Pre-Lua Check-Then-Insert Race Condition in Sliding Window Log
Before Day 42, `RedisSlidingWindowLog` executed two separate Redis operations:
1. `pipe.zcard(key)` $\to$ returns current count (e.g. 9 when limit=10).
2. If `count < limit`, execute `pipe.zadd(key, ...)`.

Under 50 concurrent requests, multiple threads executed step 1 simultaneously while `count < 10`. All of them observed `count < limit`, and each proceeded to execute step 2, admitting up to **18–25 requests** when the limit was strictly 10.

#### 2. The Lua Atomicity Guarantee
Redis executes Lua scripts atomically in its single-threaded event loop. When `redis_sliding_window_log.lua` runs:
- `ZREMRANGEBYSCORE` (pruning),
- `ZCARD` (cardinality check),
- `ZADD` (conditional member insertion), and
- `EXPIRE` (TTL refresh)
all execute uninterrupted as a single atomic unit. No other client command can interleave mid-script. As demonstrated in `test_redis_concurrency.py`, exactly 10 requests are allowed and 40 are blocked across 100% of test runs.
