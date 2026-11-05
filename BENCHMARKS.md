# RateFortress — Benchmark Results & Analysis

These are the benchmark results I collected while testing the algorithms across different storage setups and load generators.

---

## Key Findings

1. In-memory Python limiters run in microseconds, but they only work for a single process. Sliding Window Counter gave me the best compromise between memory usage and edge-of-window accuracy.
2. Moving to Redis dropped throughput from millions to tens of thousands per second because of network round-trips. That drop is the price of keeping counters consistent across multiple server instances.
3. Without Lua scripts, Redis had bad race conditions under concurrency. Multiple workers checked the key before any worker incremented it, letting through twice the allowed quota. Writing Lua scripts fixed that completely.
4. Switching to redis.asyncio kept FastAPI's event loop from stalling under load. The median latency improved once workers stopped blocking on synchronous Redis sockets.
5. k6 was much lighter on my machine than Locust. Locust's Gevent workers started eating CPU at higher loads, which skewed the timings, while k6 stayed steady.
6. A sudden traffic spike to 1,500 connections failed because the OS socket backlog filled up immediately, dropping connections before Python ever saw them. Once traffic steadied, memory remained flat over time, showing that the Redis TTLs and connection pools were not leaking.

---

## Test Environment

- OS: Windows (x86_64)
- Python Version: 3.13.13
- ASGI Server: Uvicorn (FastAPI)
- Load Generation Tools: Locust 2.47.0 (Python/Gevent), k6 v0.56.0 (Go/Sobek)
- Redis Engines: Redis 7+ / redis.asyncio with atomic Lua scripts; fakeredis shared server for deterministic headless runs.

---

## Round 1: In-Memory Pure Python Implementations (Days 11–21)

Harness: `benchmarks/run_benchmark.py` (10,000 requests, 100 simulated clients, limit = 50 reqs / 10s)

| Algorithm | Throughput (req/s) | Allowed | Blocked | Elapsed (s) | Memory / User | Burst Tolerance | Boundary Leak? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Fixed Window Counter** | **2,819,761 req/s** | 5,000 | 5,000 | 0.0035s | $O(1)$ (~48 bytes) | None | **Yes (up to 2x limit)** |
| **Sliding Window Log** | **3,471,620 req/s** | 5,000 | 5,000 | 0.0029s | $O(N)$ (timestamps) | None | **No (Strict Guarantee)** |
| **Sliding Window Counter** | **2,115,551 req/s** | 5,000 | 5,000 | 0.0047s | $O(1)$ (~64 bytes) | None | **No (Smooth Approximation)** |
| **Token Bucket** | **2,066,073 req/s** | 5,000 | 5,000 | 0.0048s | $O(1)$ (~48 bytes) | Configurable burst | **No** |
| **Leaky Bucket** | **2,580,845 req/s** | 5,000 | 5,000 | 0.0039s | $O(\text{Queue size})$ | Strict queue outflow | **No** |
| **GCRA (Cell Rate)** | **3,303,492 req/s** | 5,000 | 5,000 | 0.0030s | $O(1)$ (~32 bytes) | Configurable tolerance $\tau$ | **No** |

### Window Boundary Behavior

When testing Fixed Window Counter with bursts right at the boundary between two windows, it allowed double the quota. The first window reset right as the second burst arrived. Sliding Window Log and Sliding Window Counter both caught that burst and capped it properly.

---

## Round 2: Middleware Integration & HTTP Burst Throttling (Day 31)

Tested via `loadtests/manual_load_burst.py` against FastAPI RateLimitMiddleware:
- Target Endpoint: `/api/test` (Limit: 10 requests / 60 seconds, Token Bucket)
- Client Identity: Anonymous IP (`203.0.113.195`)

| Request Range | Status Code | Remaining Header | Retry-After Header | Middleware Action |
| :--- | :--- | :--- | :--- | :--- |
| **#1 to #10** | **HTTP 200 OK** | 9 down to 0 | 0s (10th: 6s) | Allowed (Token consumed) |
| **#11 to #30** | **HTTP 429 Too Many Requests** | 0 | 6s | **Throttled (Quota exhausted)** |

I sent 30 requests in a loop to verify that the middleware switches from 200 to 429 on the 11th request and sends back the expected headers.

---

## Round 3: Distributed Redis Backend & Concurrency (Days 35–45)

Tested via `benchmarks/run_redis_benchmark.py` and `tests/test_redis_concurrency.py` (50 concurrent worker threads, limit=10):

| Algorithm Implementation | Storage Backend | Atomicity Model | Throughput (req/s) | 50-Thread Concurrent Stress (Limit=10) | Over-Admission Leak? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Fixed Window Counter** | Redis (`INCR` + `EXPIRE`) | Redis Atomic `INCR` | **43,334 req/s** | 10 Allowed / 40 Blocked | **Zero (0%)** |
| **Sliding Window Counter (Lua)** | Redis Key-Value (`GET` + `INCR`) | **Atomic Lua Script** | **7,213 req/s** | 10 Allowed / 40 Blocked | **Zero (0%)** |
| **Sliding Window Log (Lua)** | Redis Sorted Set (`ZSET`) | **Atomic Lua Script** | **5,858 req/s** | 10 Allowed / 40 Blocked | **Zero (0%)** |
| **Token Bucket (Lua)** | Redis Hash (`HMGET`/`HMSET`) | **Atomic Lua Script** | **6,533 req/s** | 10 Allowed / 40 Blocked | **Zero (0%)** |
| **Leaky Bucket (Lua)** | Redis Hash (`HMGET`/`HMSET`) | **Atomic Lua Script** | **6,310 req/s** | 10 Allowed / 40 Blocked | **Zero (0%)** |
| **GCRA (Lua)** | Redis String (`GET`/`SET`) | **Atomic Lua Script** | **6,695 req/s** | 10 Allowed / 40 Blocked | **Zero (0%)** |

### Why Lua Scripting Was Necessary

When I tested Redis without Lua scripts using 50 concurrent threads, requests would read the count before another thread had incremented it. As a result, 18 to 25 requests slipped through a limit of 10. Moving the check and increment logic into single Lua scripts ran atomically inside Redis and stopped the leaks.

---

## Round 4: Production Load Testing with Locust (Days 46–50)

Tested via `loadtests/run_load_tests.py` using Locust 2.47.0 across multi-tenant API traffic:

| Concurrency Tier | Architecture / Backend | Throughput (req/s) | p50 Median (ms) | p95 Latency (ms) | p99 Latency (ms) | Error / Failure Rate (%) | Performance Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10 Users** (Day 46) | In-Memory Baseline | **26.6 req/s** | 2.0 ms | 3.0 ms | 5.0 ms | 0.0% | Ultra-low latency |
| **100 Users** (Day 47) | In-Memory Baseline | **225.2 req/s** | 2.0 ms | 4.0 ms | 8.0 ms | 0.0% | Steady-state optimal |
| **500 Users** (Day 48) | **Sync Redis** (Event-Loop Blocking) | **1,065.7 req/s** | 17.0 ms | 57.0 ms | 110.0 ms | 0.0% | Event loop queueing observed |
| **500 Users** (Day 48) | **Async Redis** (`redis.asyncio`) | **1,080.1 req/s** | **13.0 ms** | **56.0 ms** | **110.0 ms** | 0.0% | **23.5% lower median latency** |
| **1,000 Users** (Day 49) | Async Redis (`redis.asyncio`) | **1,308.4 req/s** | 120.0 ms | 270.0 ms | 2,200.0 ms | 0.8% | High concurrency plateau |
| **1,500 Users Stress** (Day 49) | Async Redis (Breaking Point) | **1,420.6 req/s** | 210.0 ms | **2,200.0 ms** | **2,800.0 ms** | **9.9%** | **Capacity Ceiling Exceeded** |

I ran Locust against the gateway with different user counts to see where it saturated. Under 500 concurrent users, the sync Redis client blocked the event loop and increased median latency, whereas the async client stayed responsive.

---

## Round 5: Load Testing with k6, Spike & Soak Testing (Days 52–56)

### Benchmark Matrix: k6 vs. Locust vs. Spike vs. Soak

| Test Scenario / Load Pattern | Load Engine | Concurrency Profile | Throughput (req/s) | p50 Median (ms) | p95 Latency (ms) | p99 Latency (ms) | Error / Failure Rate (%) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ramping Comparison (Day 52/53)** | **k6 (Go Engine)** | 100 $\to$ 500 VUs ramp | **865.1 req/s** | **18.7 ms** | **134.1 ms** | **185.0 ms** | **0.0%** |
| **Ramping Comparison (Day 53)** | **Locust (Python/Gevent)** | 100 $\to$ 500 users ramp | **991.2 req/s** | **19.0 ms** | **98.0 ms** | **170.0 ms** | **0.0%** |
| **Instant Spike Shock (Day 54)** | **k6 (Go Engine)** | 10 $\to$ 1,500 VUs instant | **5,509.2 req/s** | 48.3 ms | 234.9 ms | 410.0 ms | **85.5% (TCP Resets)** |
| **Sustained Soak Test (Day 55)** | **k6 (Go Engine)** | 120 VUs steady-state | **1,134.8 req/s** | **4.2 ms** | **9.6 ms** | **15.2 ms** | **0.0%** |

### Comparing Locust and k6

Locust runs Python code on greenlets. At 500 users, Python CPU usage spiked on my machine and started adding jitter to the measurements. k6 runs compiled Go with lightweight goroutines, generating load without choking the machine.

### Spike Test Failures

I pushed an instant spike from 10 to 1,500 virtual users within three seconds to see what would break. The operating system's TCP listen backlog filled up almost instantly, so connection attempts were dropped with TCP resets before reaching Uvicorn. When traffic returned to 10 users, latencies dropped back under 5 ms without lingering issues.

### Soak Testing Memory

I kept 120 virtual users sending requests over a continuous period while tracking process memory with psutil. The process RSS stayed around 4.5 MB throughout the run without drifting up. That confirmed the Redis keys have proper TTLs and the async connection pool does not leak sockets.

---

## Architectural Limits: In-Memory Priority Queue vs Distributed Semaphores

The in-memory min-heap priority queue runs in single-digit microseconds, but it only exists within a single worker process. If I run multiple Uvicorn workers, each worker has its own queue and its own active request count.

That means total admission scales with worker count, and a busy worker cannot shed work to an idle worker. To solve that across multiple instances, I would need to move the priority queue and concurrency semaphores into Redis sorted sets.

---

## Visual Benchmark Artifacts

1. Locust Concurrency Matrix (10 to 1,500 Users): `loadtests/results/load_test_latency_comparison.png`
2. k6 vs. Locust Latency Comparison: `loadtests/results/k6_vs_locust_comparison.png`
3. Soak Test Memory Stability: `loadtests/results/soak_test_memory_stability.png`
