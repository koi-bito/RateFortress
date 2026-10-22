# RateFortress — Daily Engineering Log & Learnings

A structured record of architectural decisions, DSA insights, failure modes, and lessons learned across the 29-week engineering roadmap.

---

## 📅 Week 0 — Foundations (Days 1–5)

### Day 1 — Why Rate Limiting Exists
- **Core Concept:** Rate limiting protects services from denial of service (DoS), cascading downstream failures, brute-force/credential-stuffing attacks, and unfair resource monopolization ("noisy neighbors" in multi-tenant environments).
- **Two Concrete Scenarios Without Rate Limiting:**
  1. *Resource Exhaustion / Database Crash:* An unthrottled search or analytics endpoint receiving 10,000 requests/sec will saturate database connection pools and CPU, knocking the entire application offline for all legitimate users.
  2. *Economic / Free-Tier Exploitation:* Attackers can script automated accounts to spam free-tier generative AI endpoints or SMS verification services, running up thousands of dollars in third-party API bills in minutes.

### Day 2 — The Five Core Algorithms
- **Payments API vs. Search Autocomplete:**
  - *Payments API:* **Token Bucket** or **Sliding Window Log**. Payments cannot tolerate boundary bursts that overwhelm banking settlement gateways, but users should never face silent drops; Token Bucket allows small bursts while strictly metering the steady-state refill rate.
  - *Search Autocomplete:* **Sliding Window Counter** or **Fixed Window Counter**. Search suggestions require ultra-low latency (<5ms) and high throughput. An approximation like Sliding Window Counter has $O(1)$ memory, negligible CPU overhead, and dropping a stray keystroke is acceptable compared to adding latency to query evaluation.

### Day 3 — DSA: Hashmaps, Deques & Circular Buffers
- **Why `collections.deque` over `list`:** A standard Python `list` is a dynamic array. Popping an element from the front (`list.pop(0)`) requires shifting all remaining $n-1$ elements in memory, yielding $O(n)$ time complexity per eviction. For a sliding window log handling high request volume, $O(n)$ evictions destroy performance. `collections.deque` is implemented as a doubly linked block list, providing true $O(1)$ amortized `popleft()` and `append()`.

### Day 4 — DSA: Heaps & Consistent Hashing
- **Min-Heaps vs. Sorted Lists:** A min-heap provides $O(\log n)$ insertion and $O(1)$ peek ($O(\log n)$ pop) for priority operations. Maintaining a sorted list requires $O(n)$ insertion time. For dynamic priority queues, a min-heap scales efficiently.

### Day 5 — Project Scoping & Manual Simulation
- **Algorithm Differences Under Boundary Bursts:** Simulating 5 requests / 10s window at boundary $t=9, 10$: Fixed Window allows 5 requests at $t=9$ and another 5 at $t=10$ (10 requests in 2 seconds = 2x limit spike). Sliding Window Log and Sliding Window Counter both detect the rolling 10-second footprint and reject the boundary burst.

---

## 📅 Week 1 — Environment Setup & Project Scaffold (Days 6–10)

### Day 6 — Modular Architecture Separation
- **Why separate `algorithms/`, `middleware/`, and `api/`:** Clean separation of concerns allows testing pure algorithmic logic in isolation, swappable storage engines, and embedding limiters into any ASGI/gRPC middleware without rewriting business logic.

### Day 7 — Commit Message Conventions
- **Standard Convention Adopted:** `feat:`, `test:`, `perf:`, `refactor:`, `docs:`, `fix:`, `ci:`.

### Day 8 — Test-Driven Development (TDD)
- **Why Write Tests First:** Establishes clear boundary conditions (limit - 1, limit, limit + 1, rollover resets) before asynchronous HTTP concurrency complicates debugging.

### Day 9 — Unified Benchmark Harness
- **Why a Single Benchmark Harness:** Ensures unbiased, apples-to-apples comparisons by isolating algorithmic data structures as the sole independent variable.

### Day 10 — Week 1 Review
- **Reflection:** Scaffolded core directory structure, configured isolated Python virtual environment, integrated pytest, established baseline benchmark harness, and validated clean code formatting.

---

## 📅 Week 2 — Fixed Window & Sliding Window Log (Days 11–15)

### Day 11 — Fixed Window Counter Mechanics
- **The Boundary Burst Problem:** Fixed Window evaluates `current_window = int(now // window_seconds)`. Traffic clustered at window boundaries allows up to $2 \times \text{limit}$ in a rolling window of length $T$.
- **Complexity:** $O(1)$ time, $O(1)$ memory per client.

### Day 12 — Testing & Benchmarking Fixed Window
- **Throughput:** Achieved **~2.82M req/s** in in-memory pure Python.

### Day 13 — Sliding Window Log Mechanics
- **Precision with Deques:** Sliding Window Log records timestamps in a `collections.deque`. Timestamps $\le \text{now} - \text{window}$ are popped from the left.
- **Tradeoff:** Storing every timestamp consumes $O(N)$ memory per active client.

### Day 14 — Testing & Benchmarking Sliding Window Log
- **Throughput:** Achieved **~3.47M req/s** in in-memory pure Python.

### Day 15 — Empirical Comparison (Fixed Window vs. Sliding Window Log)
- **Script Evidence:** `benchmarks/compare_window_boundary.py` verified that with limit=5/10s, Fixed Window leaked 10/10 requests while Sliding Window Log blocked requests 6 through 10.

---

## 📅 Week 3 — Sliding Window Counter, Token Bucket & Leaky Bucket (Days 16–21)

### Day 16 — Sliding Window Counter Mechanics
- **Weighted Approximation Math:** $\text{Estimated} = (\text{Previous Count} \times \text{Weight of Previous}) + \text{Current Count}$, where $\text{Weight of Previous} = 1 - (\text{Elapsed} / \text{Window})$.
- **Why It Beats Both Predecessors:** Provides boundary smoothing with strictly $O(1)$ memory (only 2 counters per client).

### Day 17 — Token Bucket Mechanics
- **Lazy Refill Calculation:** Tokens are refilled lazily on each request: $\Delta t = \text{now} - \text{last\_refill}$, $\text{new\_tokens} = \min(\text{capacity}, \text{tokens} + \Delta t \times \text{refill\_rate})$.
- **Industry Standard:** Accommodates legitimate short-term spikes up to `capacity` while guaranteeing long-term consumption never exceeds `refill_rate`.

### Day 18 — Leaky Bucket Mechanics
- **Constant Egress:** Requests enter a queue and leak out at a strictly uniform rate, completely eliminating downstream spikes.

### Day 19 — Full 5-Algorithm Benchmark Suite
- **Throughput Profile (Pure Python, 10k requests, 100 users):**
  - Sliding Window Log: **~3.47M req/s**
  - Fixed Window Counter: **~2.82M req/s**
  - Leaky Bucket: **~2.58M req/s**
  - Sliding Window Counter: **~2.12M req/s**
  - Token Bucket: **~2.07M req/s**

### Day 20 — DSA Practice Day: Core Patterns
- **LeetCode Patterns:** Monotonic deque (#239), Circular buffer (#362), and Min-heap stream (#703).

### Day 21 — Week 3 Review & Milestone Complete
- **Status:** All 5 foundation algorithms fully implemented and benchmarked.

---

## 📅 Week 4 — FastAPI Middleware Layer I (Days 22–27)

### Day 22 — ASGI Architecture & Uvicorn
- **What is ASGI:** Asynchronous Server Gateway Interface is the modern Python asynchronous standard. Uvicorn manages raw OS network sockets and event loops, invoking FastAPI's ASGI interface.

### Day 23 — Middleware Dispatch Pipeline
- **Request Interception:** `RateLimitMiddleware` intercepts requests before routing or database execution, returning early HTTP 429 responses.

### Day 24 — Rate Limit Headers on Every Response
- **Client Transparency:** Returns `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After` on every response, enabling client SDKs to proactively throttle before hitting errors.

### Day 25 — Per-Endpoint Quota Isolation
- **Granular Throttling:** Strict limits on expensive operations (`/api/expensive-endpoint`) without penalizing lightweight read endpoints.

### Day 26 — API Key Security & Tier Multipliers
- **Why Headers over Query Parameters:** Headers prevent credentials from being leaked to browser histories, reverse proxy logs, and `Referer` headers. Tier multipliers: Free = 1x, Paid = 10x, Enterprise = 50x.

### Day 27 — DSA Practice: Hashing & Design Patterns
- **Patterns:** LRU Cache (#146), Insert Delete GetRandom O(1) (#381), Design Twitter (#355).

---

## 📅 Week 5 — FastAPI Middleware Layer II — Tiering, Resilience & Load Prep (Days 28–33)

### Day 28 — Tiered Rate Limits with Priority Queues
- **Min-Heap Scheduling:** Implemented `PriorityRequestQueue` using `heapq` with tie-breaking counters. Enterprise (0) and Paid (1) requests are dequeued and serviced before Free (2) or Anonymous (3) requests.
- **Production Placement:** In production, request prioritization belongs at the API Gateway or ingress reverse-proxy layer (e.g. Envoy, Nginx, or an external SQS/Redis queue). Placing queues inside individual web worker processes leads to fragmented, desynchronized queues across multiple server nodes and risks dropped requests on worker restart.

### Day 29 — Endpoint Trie for Prefix Matching
- **Why Trie Beats String Scans:** Scanning an array of $N$ routes with regex or string comparisons incurs $O(N \times M)$ overhead per request. An `EndpointTrie` executes in $O(K)$ time where $K$ is the number of path segments (usually 2–5), completely independent of how many hundreds of route rules are registered.
- **Hierarchical Inheritance:** Parent rules (e.g., `/api/admin`) automatically govern nested routes (`/api/admin/users`, `/api/admin/settings`) unless explicitly overridden by a more specific child rule.

### Day 30 — Full Middleware Integration Testing
- **End-to-End Verification:** `tests/test_middleware_integration.py` confirmed trie prefix inheritance, enterprise 50x quota scaling, and circuit breaker fail-open behavior. All 46 tests pass across the suite.

### Day 31 — Live Request Burst Throttling
- **Empirical Demonstration:** `loadtests/manual_load_burst.py` fired 30 sequential requests at `/api/test` (limit=10). Requests #1–#10 succeeded with decreasing `X-RateLimit-Remaining` counts (9 down to 0). Request #11 triggered the first HTTP 429, and requests #11–#30 were all throttled with `Retry-After: 6`.

### Day 32 — Circuit Breaker & Resilience Policies
- **Fail-Open vs. Fail-Closed:**
  - *RateFortress Policy (Fail-Open):* If the storage backend (Redis) or rate limiter raises exceptions, the circuit breaker trips to `open` and allows incoming traffic to pass through. For customer-facing APIs, maximizing availability and avoiding false-positive outages takes precedence over temporary unthrottled access during an infrastructure incident.
  - *Contrast with Payments (Fail-Closed):* For payment gateways or banking settlement systems, failing closed is non-negotiable. An unthrottled payment service could execute duplicate charges, overdraft accounts, or allow fraudulent charge loops that inflict direct financial damage.

### Day 33 — Week 5 Review & Completion
- **Milestone Achieved:** The complete ASGI middleware pipeline is finished, hardened with trie matching, priority queuing, and fail-open resilience. Ready for Week 6: Distributed Redis Backend and Lua script atomicity.
