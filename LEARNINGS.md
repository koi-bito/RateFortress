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
  - *Payments API:* **Token Bucket** or **Sliding Window Log**. Payments cannot tolerate boundary bursts that overwhelm banking settlement gateways, but users should never face silent drops; Token Bucket allows small bursts (e.g., retrying a transient failure) while strictly metering the steady-state refill rate.
  - *Search Autocomplete:* **Sliding Window Counter** or **Fixed Window Counter**. Search suggestions require ultra-low latency (<5ms) and high throughput. An approximation like Sliding Window Counter has $O(1)$ memory, negligible CPU overhead, and dropping a stray keystroke is acceptable compared to adding latency to query evaluation.

### Day 3 — DSA: Hashmaps, Deques & Circular Buffers
- **Why `collections.deque` over `list`:** A standard Python `list` is a dynamic array. Popping an element from the front (`list.pop(0)`) requires shifting all remaining $n-1$ elements in memory, yielding $O(n)$ time complexity per eviction. For a sliding window log handling high request volume, $O(n)$ evictions destroy performance. `collections.deque` is implemented as a doubly linked block list, providing true $O(1)$ amortized `popleft()` and `append()`.

### Day 4 — DSA: Heaps & Consistent Hashing
- **Min-Heaps vs. Sorted Lists:** A min-heap provides $O(\log n)$ insertion and $O(1)$ peek ($O(\log n)$ pop) for priority operations. Maintaining a sorted list requires $O(n)$ insertion time (or $O(n)$ shift after $O(\log n)$ binary search insertion). For dynamic priority queues (e.g., prioritizing enterprise tier API calls ahead of free tier requests during traffic spikes), a min-heap scales efficiently.

### Day 5 — Project Scoping & Manual Simulation
- **Algorithm Differences Under Boundary Bursts:** Simulating 5 requests / 10s window at boundary $t=9, 10$: Fixed Window allows 5 requests at $t=9$ and another 5 at $t=10$ (10 requests in 2 seconds = 2x limit spike). Sliding Window Log and Sliding Window Counter both detect the rolling 10-second footprint and reject the boundary burst.

---

## 📅 Week 1 — Environment Setup & Project Scaffold (Days 6–10)

### Day 6 — Modular Architecture Separation
- **Why separate `algorithms/`, `middleware/`, and `api/`:** Clean separation of concerns allows:
  1. Testing pure algorithmic logic in isolation without spinning up HTTP test clients or ASGI event loops.
  2. Pluggability: The same rate limiter algorithm can be embedded in FastAPI middleware, a gRPC interceptor, a Celery worker, or an AWS Lambda authorizer without rewriting business logic.
  3. Swappable storage engines (In-Memory, Redis, DynamoDB) without changing the rate limiting interface.

### Day 7 — Commit Message Conventions
- **Standard Convention Adopted:**
  - `feat:` New algorithm, middleware, or system feature
  - `test:` Unit, integration, or benchmark tests
  - `perf:` Optimization or performance improvement
  - `refactor:` Code restructuring without behavior change
  - `docs:` Documentation, README, or engineering log updates
  - `fix:` Bug fix or edge-case correction
  - `ci:` Build, tooling, or workflow updates

### Day 8 — Test-Driven Development (TDD)
- **Why Write Tests First:** Writing tests before implementation establishes clear boundary conditions (e.g., what happens at limit - 1, limit, and limit + 1; exact window resets). Skipping early testing leads to subtle off-by-one errors and race conditions that are exponentially harder to debug once wrapped inside asynchronous HTTP middleware.

### Day 9 — Unified Benchmark Harness
- **Why a Single Benchmark Harness:** To ensure unbiased, apples-to-apples performance comparisons. Keeping constant user distribution, request loops, timing precision (`time.perf_counter`), and system metrics isolates algorithmic complexity and data structure overhead as the sole independent variables.

### Day 10 — Week 1 Review
- **Reflection:** Scaffolded core directory structure, configured isolated Python virtual environment, integrated pytest, established baseline benchmark harness, and validated clean code formatting with Ruff and Black. Ready to implement pure algorithms starting with Fixed Window Counter.

---

## 📅 Week 2 — Fixed Window & Sliding Window Log (Days 11–15)

### Day 11 — Fixed Window Counter Mechanics
- **The Boundary Burst Problem:** Fixed Window evaluates `current_window = int(now // window_seconds)`. If window size is 60s and limit is 100 requests, a client can send 100 requests at $t=59\text{s}$ (window 0) and another 100 requests at $t=60\text{s}$ (window 1). The service experiences 200 requests in a 2-second interval — twice the intended peak load.
- **Complexity:** $O(1)$ time, $O(1)$ memory per client.

### Day 12 — Testing & Benchmarking Fixed Window
- **Test Findings:** Validated clean reset when window rollover occurs (`sleep(window_seconds + delta)`), independent quotas per user ID, and remaining count decrements.
- **Throughput:** Achieved **~3.28M req/s** in in-memory pure Python.

### Day 13 — Sliding Window Log Mechanics
- **Precision with Deques:** Sliding Window Log records every individual timestamp in a `collections.deque`. Upon every request, timestamps $\le \text{now} - \text{window}$ are popped from the left.
- **Exact Enforcement:** Because the rolling window $[now - window, now]$ is continuously updated, boundary spikes are impossible.
- **Tradeoff:** Storing every timestamp consumes $O(N)$ memory. At $10^5$ requests per minute across $10^6$ active users, memory footprint would balloon into tens of gigabytes in Redis.

### Day 14 — Testing & Benchmarking Sliding Window Log
- **Test Findings:** Verified that slots open gradually as individual timestamps exit the rolling window, rather than releasing all quota in a single abrupt reset.
- **Throughput:** Achieved **~3.18M req/s** in in-memory pure Python.

### Day 15 — Empirical Comparison (Fixed Window vs. Sliding Window Log)
- **Script Evidence:** `benchmarks/compare_window_boundary.py` verified that with limit=5/10s, sending 5 requests at $t=8.0..9.9\text{s}$ and 5 requests at $t=10.1..10.5\text{s}$ allowed all 10 in Fixed Window Counter (100% leak) while Sliding Window Log blocked requests 6 through 10.
- **Production Choice:** For a payments API, Sliding Window Log (or Token Bucket) is mandatory because downstream bank gateways cannot survive 2x load spikes. For internal rate limiting of high-throughput read endpoints where occasional bursts are benign, Fixed Window Counter is vastly more memory-efficient.
