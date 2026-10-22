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
- **Throughput:** Achieved **~2.82M req/s** in in-memory pure Python.

### Day 13 — Sliding Window Log Mechanics
- **Precision with Deques:** Sliding Window Log records every individual timestamp in a `collections.deque`. Upon every request, timestamps $\le \text{now} - \text{window}$ are popped from the left.
- **Exact Enforcement:** Because the rolling window $[now - window, now]$ is continuously updated, boundary spikes are impossible.
- **Tradeoff:** Storing every timestamp consumes $O(N)$ memory. At $10^5$ requests per minute across $10^6$ active users, memory footprint would balloon into tens of gigabytes in Redis.

### Day 14 — Testing & Benchmarking Sliding Window Log
- **Test Findings:** Verified that slots open gradually as individual timestamps exit the rolling window, rather than releasing all quota in a single abrupt reset.
- **Throughput:** Achieved **~3.47M req/s** in in-memory pure Python.

### Day 15 — Empirical Comparison (Fixed Window vs. Sliding Window Log)
- **Script Evidence:** `benchmarks/compare_window_boundary.py` verified that with limit=5/10s, sending 5 requests at $t=8.0..9.9\text{s}$ and 5 requests at $t=10.1..10.5\text{s}$ allowed all 10 in Fixed Window Counter (100% leak) while Sliding Window Log blocked requests 6 through 10.
- **Production Choice:** For a payments API, Sliding Window Log (or Token Bucket) is mandatory because downstream bank gateways cannot survive 2x load spikes. For internal rate limiting of high-throughput read endpoints where occasional bursts are benign, Fixed Window Counter is vastly more memory-efficient.

---

## 📅 Week 3 — Sliding Window Counter, Token Bucket & Leaky Bucket (Days 16–21)

### Day 16 — Sliding Window Counter Mechanics
- **Weighted Approximation Math:** The formula is $\text{Estimated} = (\text{Previous Window Count} \times \text{Weight of Previous}) + \text{Current Window Count}$, where $\text{Weight of Previous} = 1 - (\text{Elapsed in Current Window} / \text{Window Duration})$.
- **Why It Beats Both Predecessors:** Provides boundary smoothing without storing timestamps. Memory is strictly $O(1)$ (only 2 integer counters per client), yet boundary burst error is typically $<5\%$ in production traffic.

### Day 17 — Token Bucket Mechanics
- **Lazy Refill Calculation:** Rather than maintaining background threads or cron timers constantly refilling buckets, tokens are refilled lazily on each request: $\Delta t = \text{now} - \text{last\_refill}$, $\text{new\_tokens} = \min(\text{capacity}, \text{tokens} + \Delta t \times \text{refill\_rate})$.
- **Why Stripe & GitHub Choose Token Bucket:** Real-world traffic is inherently bursty. Token Bucket accommodates legitimate short-term spikes up to `capacity` while guaranteeing long-term consumption never exceeds `refill_rate`.

### Day 18 — Leaky Bucket Mechanics
- **Constant Egress vs. Token Bucket:** Token Bucket allows bursts to pass immediately through to the backend as long as tokens exist. Leaky Bucket queues requests and leaks them at a fixed, uniform rate.
- **User Experience Contrast:** For an API consumer, Token Bucket delivers lower latency during bursts (requests execute immediately). Leaky Bucket introduces queueing delay (or drops if queue is full), but provides an absolutely flat downstream request rate, protecting fragile dependencies like legacy databases.

### Day 19 — Full 5-Algorithm Benchmark Suite
- **Throughput Profile (Pure Python, 10,000 requests, 100 users):**
  - Sliding Window Log: **~3.47M req/s**
  - Fixed Window Counter: **~2.82M req/s**
  - Leaky Bucket: **~2.58M req/s**
  - Sliding Window Counter: **~2.12M req/s**
  - Token Bucket: **~2.07M req/s**

### Day 20 — DSA Practice Day: Core Patterns
- **Sliding Window Maximum (LeetCode #239):** Monotonic deque pattern. Elements smaller than the incoming element are popped from the back; expired indices are popped from the front. Identical to timestamp eviction in Sliding Window Log.
- **Design Hit Counter (LeetCode #362):** Circular buffer / fixed bucket pattern. Modulo arithmetic `time % 300` mirrors the fixed and sliding window counter index calculations.
- **Kth Largest Element in a Stream (LeetCode #703):** Min-heap pattern of size $k$. Incoming elements maintain the top $k$ items with $O(\log k)$ push-pop.

### Day 21 — Week 3 Review & Milestone Complete
- **Status:** All 5 foundation algorithms are fully implemented, strictly typed, formatted with Black/Ruff, verified with 27 passing unit tests, and comparatively benchmarked.

---

## 📅 Week 4 — FastAPI Middleware Layer I (Days 22–27)

### Day 22 — ASGI Architecture & Uvicorn
- **What is ASGI:** Asynchronous Server Gateway Interface is the modern Python asynchronous standard (successor to synchronous WSGI like Gunicorn/Flask). It standardizes how asynchronous Python applications handle HTTP, HTTP/2, and WebSockets over `async`/`await` event loops.
- **Why FastAPI Requires Uvicorn:** FastAPI is solely an application framework responsible for request routing, schema serialization (Pydantic), and dependency injection. It does not contain an HTTP socket parser or TCP network listener. Uvicorn is the high-performance ASGI server (built on `uvloop` and `httptools`) that binds to OS network sockets, parses raw HTTP bytes, and invokes FastAPI's ASGI interface.

### Day 23 — Middleware Dispatch Pipeline
- **Request Interception:** `RateLimitMiddleware` inherits from Starlette's `BaseHTTPMiddleware`. By overriding `dispatch(request, call_next)`, rate limit evaluation happens *before* request parameters are deserialized or database transactions are opened. When limits are exceeded, an early HTTP 429 response is returned immediately, shedding server load with near-zero resource expenditure.

### Day 24 — Rate Limit Headers on Every Response
- **Why Send Headers on 200 OK:** Professional APIs (Stripe, GitHub, OpenAI) return `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After` on *every* response, not just when a client gets blocked (429).
  - *Proactive Throttling:* Client SDKs can monitor `X-RateLimit-Remaining` and voluntarily throttle or queue their own requests as the remaining quota approaches zero, avoiding unexpected exceptions.
  - *Debugging Visibility:* API consumers can immediately see their consumption without guessing how close they are to the threshold.

### Day 25 — Per-Endpoint Quota Isolation
- **Granular Throttling:** Different endpoints have radically different resource costs. While a lightweight health check `/health` can support 200 req/min, a resource-intensive analytics or AI endpoint `/api/expensive-endpoint` must be clamped to 5 or 10 req/min. Isolating quotas by path ensures an attacker spamming an expensive endpoint does not exhaust the user's quota for unrelated lightweight endpoints.

### Day 26 — API Key Security & Tier Multipliers
- **Why Headers over Query Parameters:** API keys must *never* be accepted in URL query parameters (e.g. `?api_key=xyz`):
  1. URLs are logged in plain text in browser histories, proxy logs, load balancer access logs (Nginx/Cloudflare), and application APM traces.
  2. The HTTP `Referer` header automatically leaks query parameters to external third-party domains when clicking links.
  3. Putting keys in headers (`X-API-Key` or `Authorization: Bearer`) ensures sensitive credentials remain shielded from standard access logs and referrers.
- **Tier-Based Multipliers:** Enabled dynamic multiplier resolution (`key_free_abc` = 1x, `key_paid_xyz` = 10x, `key_enterprise_999` = 50x), multiplying nominal endpoint limits accordingly.

### Day 27 — DSA Practice: Hashing & Design Patterns
- **LRU Cache (LeetCode #146):** Hashmap + Doubly Linked List. How it applies to RateFortress: If millions of distinct IP addresses hit the gateway, storing unbounded per-IP state in memory leads to out-of-memory (OOM) crashes. An LRU Cache eviction policy caps the active tracking set to the top $K$ most recent users.
- **Insert Delete GetRandom O(1) (LeetCode #381):** Hashmap (value $\to$ index) + Dynamic Array. Allows $O(1)$ deletes by swapping the target element with the last element in the array before popping.
- **Design Twitter (LeetCode #355):** Combines Hashmaps for follow graphs and Min/Max-Heaps for $k$-way merge of user timelines. Directly mirrors our Week 5 tiered priority queue architecture.
