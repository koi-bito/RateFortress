# RateFortress — Distributed Rate Limiter Engine — Implementation Plan

### Goal: Build a production-grade, distributed rate limiting engine from first principles — covering DSA, backend API design, distributed systems, load testing, observability, security, billing, and deployment — then push past the core build into the dimensions most portfolio projects never touch.

### Pace: ~3–4 hrs/day | 29 weeks / 140 days, plus a 3-day senior-review addendum (143 days total) | No GPU required | Stack: Python, FastAPI, Go, Redis, Docker, Prometheus, Grafana, Loki, OpenTelemetry, Locust, k6, Toxiproxy, Stripe, GitHub Actions, AWS EC2 / Render

---

> **How to use this plan:**
> Each day has one clear goal, exact steps, and a "you're done when" checkpoint.
> Estimated time per day: 3–4 hours.
> Keep a file called `LEARNINGS.md` in your repo. Write 3–5 sentences every day — what you learned, what confused you, how you fixed it.
> This plan has no ceiling on your request — it now runs 29 weeks / 140 days, well past 3-4 months at a steady pace. Skipping a day and resuming later is fine. Skipping understanding is not.
> **Why this project:** Rate limiting sits at the exact intersection of core SWE fundamentals (DSA, system design) and backend/AI infra responsibilities that show up constantly in job descriptions — auth, throttling, API design, distributed state. Dedicated DSA practice days are woven in throughout, not just applied DSA inside the project.
> **What makes this version worth being proud of:** Weeks 0–20 (Days 1–100) build the core system end to end. Weeks 21–29 (Days 101–140) go further than almost anyone does at this stage — attacking your own system the way real abusers would (full circle back to the "fake free trials" problem that started this), practicing the exact system design interview question this project maps to, building a real admin dashboard and real Stripe billing, chaos-testing your own resilience claims instead of just asserting them, and even stepping into Go to measure a language tradeoff with real numbers instead of a resume keyword.

---

## WEEK 0 — Foundations (Days 1–5)

> **Goal:** Understand rate limiting and the DSA behind it deeply before writing a single line of production code. This week prevents weeks of confusion later.

---

### Day 1 — What Is Rate Limiting & Why It Exists

**Time:** 3 hrs

**What you're learning:** The core problem rate limiting solves, and why almost every production API needs it.

**Tasks:**

1. Read about why rate limiting exists: preventing abuse (fake free-trial farming, credential stuffing, scraping), protecting infra from overload, enforcing pricing tiers (free vs paid API quotas), and ensuring fair usage across tenants.
2. Search and skim how real companies describe their limits: Stripe's API rate limit docs, GitHub's API rate limit docs, OpenAI's rate limit docs. Note what unit they limit on (requests/min, tokens/min, concurrent requests).
3. Write in `LEARNINGS.md`: In your own words, what breaks if an API has NO rate limiting at all? Give two concrete scenarios.

**You're done when:** You can explain to a non-technical friend why Twitter or Stripe can't let anyone hit their API unlimited times per second.

---

### Day 2 — The Five Core Algorithms (Conceptual)

**Time:** 3–4 hrs

**What you're learning:** The five standard rate limiting algorithms, conceptually, with no code yet.

**Tasks:**

1. Search "rate limiting algorithms explained" and read through one solid blog post covering all five:
   - **Fixed Window Counter** — count requests in a fixed time block (e.g., 0:00–0:59), reset every minute.
   - **Sliding Window Log** — store a timestamp per request, count how many fall within the last N seconds.
   - **Sliding Window Counter** — a weighted blend of the current and previous fixed windows, to smooth out the boundary problem.
   - **Token Bucket** — a bucket refills with tokens at a fixed rate; each request consumes a token; empty bucket = rejected.
   - **Leaky Bucket** — requests queue up and "leak out" at a constant rate, smoothing bursts.
2. For each algorithm, write one sentence: what's its biggest weakness?
   - Fixed Window → burst at window boundaries (2x traffic possible right at the edge)
   - Sliding Window Log → memory-heavy (stores every timestamp)
   - Sliding Window Counter → an approximation, not exact
   - Token Bucket → allows short bursts, which may or may not be desirable
   - Leaky Bucket → strict output rate, no bursts allowed at all even when idle time was banked
3. Write in `LEARNINGS.md`: Which algorithm would you pick for a payments API vs a search-autocomplete API, and why?

**You're done when:** You can describe all five algorithms from memory without looking anything up.

---

### Day 3 — DSA Building Blocks: Hashmaps, Deques & Circular Buffers

**Time:** 3 hrs

**What you're learning:** The exact data structures that make each algorithm work, before you tie them to rate limiting.

**Tasks:**

1. Refresh hashmaps: O(1) average lookup/insert, how collisions are handled. This is what you'll use to track per-user counters.
2. Refresh `collections.deque` in Python — why it gives O(1) append/pop from both ends (unlike a list, which is O(n) from the front). Run this:

```python
from collections import deque
import time

d = deque()
d.append(time.time())
d.append(time.time())
print(d)
# popleft() removes from the front in O(1) — critical for sliding window log
d.popleft()
print(d)
```

3. Refresh circular buffers conceptually — fixed-size buffer that wraps around, useful when you only care about the last N events and want to overwrite the oldest.
4. Write in `LEARNINGS.md`: Why is a Python `list` a bad choice for a sliding window log if you need to remove old timestamps from the front constantly?

**You're done when:** You understand why `deque` beats `list` for this use case, concretely (not just "it's faster").

---

### Day 4 — DSA Building Blocks: Heaps & Hashing for Distribution

**Time:** 3 hrs

**What you're learning:** The two more advanced structures you'll need later for tiered limits and distributed rate limiting.

**Tasks:**

1. Refresh min-heaps (`heapq` in Python) — O(log n) insert/pop-min. You'll use this later for priority-based throttling (serve paid-tier requests before free-tier when both are queued).

```python
import heapq

queue = []
heapq.heappush(queue, (1, "free_user_request"))   # lower number = higher priority
heapq.heappush(queue, (0, "paid_user_request"))
print(heapq.heappop(queue))  # paid_user_request comes out first
```

2. Read a short explainer on **consistent hashing** — why it matters when you eventually shard rate-limit state across multiple Redis nodes (not required for a single Redis instance, but good to understand conceptually now).
3. Write in `LEARNINGS.md`: What problem does a min-heap solve that a simple sorted list doesn't?

**You're done when:** You can explain why popping the minimum from a heap is O(log n) instead of O(n).

---

### Day 5 — Manual Simulation, Real-World Cases & Project Scoping

**Time:** 4 hrs

**What you're learning:** Tying everything together by hand, and locking in your project's final scope before writing code.

**Tasks:**

1. On paper (or Excalidraw), simulate this scenario manually for each of the 5 algorithms: "Limit = 5 requests per 10 seconds. Requests arrive at t=0,1,2,3,4,9,10,11,12." For each algorithm, mark which requests get ALLOWED vs BLOCKED. This single exercise is where real understanding clicks.
2. Read how Stripe, GitHub, and OpenAI structure their rate limit response headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After`). You'll replicate this pattern later.
3. Write your final project scope in `README.md` (create the repo structure on Day 6, but draft this text now):
   - Project name: **RateFortress**
   - What it is: a distributed rate limiting engine supporting 5 algorithms, exposed as a pluggable FastAPI middleware, backed by Redis, benchmarked under load, observable via Prometheus/Grafana, and deployed publicly.
4. Write in `LEARNINGS.md`: A one-paragraph summary of what you learned this week, in your own words.

**You're done when:** You've hand-simulated all 5 algorithms on the same input and can see exactly how their outputs differ.

---

## WEEK 1 — Environment Setup & Project Scaffold (Days 6–10)

> **Goal:** Get your full local development environment and repo structure working without errors, so every week after this is friction-free.

---

### Day 6 — Python Environment & Project Structure

**Time:** 3 hrs

**What you're doing:** Setting up a clean, isolated Python environment and the folder structure you'll use for the entire project.

**Tasks:**

1. Install Python 3.11+ if you don't already have it set up for this project.
2. Create and activate a virtual environment:

```bash
python -m venv ratefortress_env

# Mac/Linux:
source ratefortress_env/bin/activate
# Windows:
ratefortress_env\Scripts\activate
```

3. Create the folder structure:

```
ratefortress/
├── src/
│   ├── algorithms/
│   ├── middleware/
│   ├── api/
│   └── storage/
├── tests/
├── benchmarks/
├── loadtests/
├── monitoring/
├── docs/
├── README.md
├── LEARNINGS.md
├── BENCHMARKS.md
├── requirements.txt
└── .gitignore
```

4. Create `.gitignore`:

```
__pycache__/
*.pyc
.env
ratefortress_env/
*.log
```

**You're done when:** Your folder structure exists and the virtual environment activates cleanly.

**Write in LEARNINGS.md:** What is the purpose of separating `algorithms/` from `middleware/` from `api/`? Why not just put everything in one file?

---

### Day 7 — GitHub Repo + Git Workflow

**Time:** 3 hrs

**What you're doing:** Getting your code under version control with a clean commit history from day one.

**Tasks:**

1. Create a new public GitHub repo called `ratefortress`.
2. Configure Git if needed, then connect your local folder:

```bash
git init
git remote add origin https://github.com/your-username/ratefortress.git
git add .
git commit -m "initial project structure"
git branch -M main
git push -u origin main
```

3. Adopt a simple daily commit habit: one commit per "done when" checkpoint, with a message describing what you built (not "fix" or "update").
4. Install the `black` and `ruff` formatters/linters so your code stays clean from day one:

```bash
pip install black ruff
```

**You're done when:** Your repo is live on GitHub with the full folder structure committed.

**Write in LEARNINGS.md:** Write a commit message convention you'll stick to for the rest of the project (e.g., `feat:`, `test:`, `fix:`, `docs:`).

---

### Day 8 — Testing Framework (pytest) Setup

**Time:** 3 hrs

**What you're doing:** Getting `pytest` wired up before you write a single algorithm, so every algorithm you build from Week 2 onward gets tested immediately.

**Tasks:**

1. Install pytest and create your first dummy test to confirm the setup works:

```bash
pip install pytest pytest-benchmark
```

2. Create `tests/test_sanity.py`:

```python
def test_sanity():
    assert 1 + 1 == 2
```

3. Run it:

```bash
pytest -v
```

4. Create `requirements.txt` so far:

```bash
pip freeze > requirements.txt
```

**You're done when:** `pytest -v` runs and passes with zero errors.

**Write in LEARNINGS.md:** Why do you write tests BEFORE building features, instead of after? What's the risk of skipping this?

---

### Day 9 — Benchmarking Harness Skeleton

**Time:** 3 hrs

**What you're doing:** Building a reusable benchmarking script skeleton now, so every algorithm you implement from Week 2 onward can be benchmarked the same way (apples-to-apples comparison later).

**Tasks:**

1. Create `benchmarks/run_benchmark.py`:

```python
"""
Reusable benchmark harness for rate limiting algorithms.
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
    print(f"\n--- {name} ---")
    print(f"Total requests: {num_requests}")
    print(f"Allowed: {allowed} | Blocked: {blocked}")
    print(f"Time: {elapsed:.4f}s | Throughput: {num_requests/elapsed:.0f} req/s")
    return {"name": name, "allowed": allowed, "blocked": blocked, "elapsed": elapsed}

if __name__ == "__main__":
    print("Benchmark harness ready. Algorithms will be plugged in starting Week 2.")
```

2. Run it once just to confirm it executes cleanly (it won't benchmark anything real yet — that starts Week 2).

**You're done when:** `python benchmarks/run_benchmark.py` runs without errors and prints the placeholder message.

**Write in LEARNINGS.md:** Why benchmark with the SAME harness for every algorithm instead of writing a new benchmarking script each time?

---

### Day 10 — Week 0+1 Review + README v1

**Time:** 3 hrs

**Tasks:**

1. Review: do all your folders, tests, and benchmark harness work together without errors?
2. Write `README.md` v1:
   - What RateFortress is (one paragraph)
   - Tech stack (even if some isn't installed yet — this is the target stack)
   - Status: "Week 1 — Environment & Scaffold Complete"
3. Update `LEARNINGS.md` with a week summary: what was the hardest part so far?
4. Commit and push everything.

**You're done when:** Your repo has a clean README, passing tests, and commits for every day this week.

---

## WEEK 2 — Fixed Window & Sliding Window Log (Days 11–15)

> **Goal:** Implement your first two algorithms in pure Python — no frameworks, no Redis yet. Just the logic, tested and benchmarked.

---

### Day 11 — Implement Fixed Window Counter

**Time:** 3–4 hrs

**What you're building:** The simplest rate limiter — a per-user counter that resets every fixed time window.

**Tasks:**

1. Create `src/algorithms/fixed_window.py`:

```python
import time
from collections import defaultdict

class FixedWindowCounter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.counters = defaultdict(int)
        self.window_start = defaultdict(float)

    def is_allowed(self, user_id: str) -> bool:
        now = time.time()
        current_window = int(now // self.window_seconds)

        if self.window_start[user_id] != current_window:
            # new window — reset
            self.window_start[user_id] = current_window
            self.counters[user_id] = 0

        if self.counters[user_id] < self.limit:
            self.counters[user_id] += 1
            return True
        return False
```

2. Manually test it in a Python shell: call `is_allowed("u1")` 6 times with `limit=5` and confirm the 6th call returns `False`.

**You're done when:** You can manually trigger a block by exceeding the limit.

**Write in LEARNINGS.md:** Why does this algorithm allow up to 2x the limit right at the window boundary? Walk through a concrete example.

---

### Day 12 — Test & Benchmark Fixed Window Counter

**Time:** 3 hrs

**Tasks:**

1. Create `tests/test_fixed_window.py`:

```python
from src.algorithms.fixed_window import FixedWindowCounter
import time

def test_allows_up_to_limit():
    limiter = FixedWindowCounter(limit=3, window_seconds=10)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False  # 4th request blocked

def test_resets_after_window():
    limiter = FixedWindowCounter(limit=1, window_seconds=1)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u1") is False
    time.sleep(1.1)
    assert limiter.is_allowed("u1") is True  # window reset

def test_independent_per_user():
    limiter = FixedWindowCounter(limit=1, window_seconds=10)
    assert limiter.is_allowed("u1") is True
    assert limiter.is_allowed("u2") is True  # different user, own limit
```

2. Run `pytest -v` — all three should pass.
3. Plug it into your benchmark harness from Day 9 and run it against 10,000 requests across 100 users. Record the throughput number — you'll compare this against every other algorithm later.

**You're done when:** All tests pass and you have a recorded throughput number for Fixed Window Counter.

---

### Day 13 — Implement Sliding Window Log

**Time:** 4 hrs

**What you're building:** The most accurate (but most memory-heavy) algorithm — storing every request timestamp per user.

**Tasks:**

1. Create `src/algorithms/sliding_window_log.py`:

```python
import time
from collections import defaultdict, deque

class SlidingWindowLog:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.logs = defaultdict(deque)

    def is_allowed(self, user_id: str) -> bool:
        now = time.time()
        log = self.logs[user_id]

        # Drop timestamps older than the window — O(1) per removal from the left
        while log and log[0] <= now - self.window_seconds:
            log.popleft()

        if len(log) < self.limit:
            log.append(now)
            return True
        return False
```

2. Test it manually: send 5 requests instantly with `limit=5`, confirm the 6th is blocked, then wait out the window and confirm it opens back up.

**You're done when:** The 6th immediate request is blocked and requests are allowed again after the window passes.

**Write in LEARNINGS.md:** Why is this algorithm exact (no boundary burst problem) but memory-heavier than Fixed Window?

---

### Day 14 — Test & Benchmark Sliding Window Log

**Time:** 3 hrs

**Tasks:**

1. Write `tests/test_sliding_window_log.py` mirroring Day 12's structure (allows-up-to-limit, blocks-over-limit, resets-after-window-slides, independent-per-user).
2. Run `pytest -v`.
3. Benchmark it with the same 10,000-request/100-user harness. Compare its throughput and memory footprint against Fixed Window Counter from Day 12 — note the difference in `BENCHMARKS.md`.

**You're done when:** Tests pass and you have a side-by-side throughput number against Fixed Window Counter.

---

### Day 15 — Compare Fixed Window vs Sliding Window Log

**Time:** 2–3 hrs

**Tasks:**

1. Write a short comparison script that feeds the EXACT same burst-at-boundary scenario (from Day 5's paper exercise) into both algorithms and prints the result side by side.
2. Confirm with real code what you predicted on paper in Week 0: Fixed Window allows a burst at the boundary; Sliding Window Log does not.
3. Document this comparison (with the printed output) in `BENCHMARKS.md` — this is your first real "tradeoff evidence," useful later for interviews.
4. Commit and push.

**You're done when:** You have code-verified proof of the boundary-burst difference between the two algorithms.

**Write in LEARNINGS.md:** If you had to pick just one of these two for a payments API, which would you choose and why?

---

## WEEK 3 — Sliding Window Counter, Token Bucket & Leaky Bucket (Days 16–21)

> **Goal:** Finish all 5 algorithms in pure Python, benchmark them together, and lock in the sliding-window/heap DSA with dedicated practice.

---

### Day 16 — Implement Sliding Window Counter

**Time:** 4 hrs

**What you're building:** A middle-ground algorithm — more accurate than Fixed Window, cheaper than Sliding Window Log.

**Tasks:**

1. Create `src/algorithms/sliding_window_counter.py`:

```python
import time
from collections import defaultdict

class SlidingWindowCounter:
    """Blends the previous and current fixed window counts, weighted by
    how far into the current window we are, to approximate a true sliding window."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.current_window = defaultdict(int)
        self.previous_window = defaultdict(int)
        self.window_id = defaultdict(int)

    def is_allowed(self, user_id: str) -> bool:
        now = time.time()
        current_id = int(now // self.window_seconds)
        elapsed_in_window = now % self.window_seconds
        weight_of_previous = 1 - (elapsed_in_window / self.window_seconds)

        if self.window_id[user_id] != current_id:
            # Shift: what was "current" becomes "previous"
            if current_id - self.window_id[user_id] == 1:
                self.previous_window[user_id] = self.current_window[user_id]
            else:
                self.previous_window[user_id] = 0
            self.current_window[user_id] = 0
            self.window_id[user_id] = current_id

        estimated_count = (
            self.previous_window[user_id] * weight_of_previous
            + self.current_window[user_id]
        )

        if estimated_count < self.limit:
            self.current_window[user_id] += 1
            return True
        return False
```

2. Write unit tests mirroring the pattern from Day 12/14.
3. Write in `LEARNINGS.md`: What does "weighted by how far into the window we are" actually mean? Walk through the math with the previous window at 50% weight.

**You're done when:** Tests pass and you can explain the weighting formula without looking at the code.

---

### Day 17 — Implement Token Bucket

**Time:** 4 hrs

**What you're building:** The algorithm that allows controlled bursts — tokens refill at a steady rate, requests spend tokens.

**Tasks:**

1. Create `src/algorithms/token_bucket.py`:

```python
import time
from collections import defaultdict

class TokenBucket:
    def __init__(self, capacity: int, refill_rate_per_sec: float):
        self.capacity = capacity
        self.refill_rate = refill_rate_per_sec
        self.tokens = defaultdict(lambda: capacity)
        self.last_refill = defaultdict(time.time)

    def is_allowed(self, user_id: str) -> bool:
        now = time.time()
        elapsed = now - self.last_refill[user_id]
        refill_amount = elapsed * self.refill_rate

        self.tokens[user_id] = min(self.capacity, self.tokens[user_id] + refill_amount)
        self.last_refill[user_id] = now

        if self.tokens[user_id] >= 1:
            self.tokens[user_id] -= 1
            return True
        return False
```

2. Write a test that proves bursting works: set `capacity=10`, send 10 requests instantly — all allowed. Send an 11th — blocked. Wait 1 second with `refill_rate_per_sec=5` — confirm 5 tokens refilled.
3. Write in `LEARNINGS.md`: Why is Token Bucket the algorithm most APIs (Stripe, GitHub) actually use in production, despite Sliding Window Log being more "exact"?

**You're done when:** Your burst test and refill test both pass.

---

### Day 18 — Implement Leaky Bucket

**Time:** 3–4 hrs

**What you're building:** The strictest algorithm — output rate is constant no matter how bursty the input is.

**Tasks:**

1. Create `src/algorithms/leaky_bucket.py`:

```python
import time
from collections import defaultdict, deque

class LeakyBucket:
    def __init__(self, capacity: int, leak_rate_per_sec: float):
        self.capacity = capacity
        self.leak_rate = leak_rate_per_sec
        self.queues = defaultdict(deque)
        self.last_leak = defaultdict(time.time)

    def _leak(self, user_id: str):
        now = time.time()
        elapsed = now - self.last_leak[user_id]
        leaked = int(elapsed * self.leak_rate)
        for _ in range(min(leaked, len(self.queues[user_id]))):
            self.queues[user_id].popleft()
        if leaked > 0:
            self.last_leak[user_id] = now

    def is_allowed(self, user_id: str) -> bool:
        self._leak(user_id)
        queue = self.queues[user_id]
        if len(queue) < self.capacity:
            queue.append(time.time())
            return True
        return False
```

2. Write a test proving the "no burst allowed" property: fill the bucket to capacity instantly, confirm the next request is blocked EVEN IF the user was previously idle for a long time (contrast this directly against Token Bucket's behavior in your test file).
3. Write in `LEARNINGS.md`: In plain English, what's the practical difference in user experience between Token Bucket and Leaky Bucket for someone calling your API?

**You're done when:** You have a test that explicitly demonstrates Token Bucket allowing a burst and Leaky Bucket rejecting the same burst pattern.

---

### Day 19 — Full Benchmark Suite — All 5 Algorithms

**Time:** 4 hrs

**What you're doing:** Running every algorithm through the exact same benchmark harness and recording results together for the first time.

**Tasks:**

1. Update `benchmarks/run_benchmark.py` to loop through all 5 algorithms with identical parameters (same limit, same window, same request pattern) and print a results table.
2. Run it and record: throughput (req/s), allowed vs blocked counts, and roughly estimate per-user memory footprint for each (Sliding Window Log stores a timestamp per request — compute what that means at scale: 1M users × 100 requests/window × 8 bytes).
3. Save the full output into `BENCHMARKS.md` as "Pure Python Benchmark — Round 1."

**You're done when:** `BENCHMARKS.md` has a results table comparing all 5 algorithms on throughput and memory.

**Write in LEARNINGS.md:** Which algorithm surprised you most in terms of performance, and why?

---

### Day 20 — DSA Practice Day: Sliding Window & Heap Problems

**Time:** 3–4 hrs

**What you're doing:** Stepping outside the project to directly sharpen the DSA patterns you just used, on classic standalone problems — this is the dedicated DSA-sharpening piece, separate from applying it inside the project.

**Tasks:**

1. Solve these on LeetCode (or any judge of your choice), timing yourself, no looking up solutions for the first 25 minutes per problem:
   - "Sliding Window Maximum" (hard) — deque-based, directly mirrors the deque pattern from your Sliding Window Log.
   - "Design Hit Counter" (medium) — nearly identical in spirit to Fixed/Sliding Window Counter.
   - "Kth Largest Element in a Stream" (easy/medium) — min-heap, same pattern as your Day 4 priority queue warm-up.
2. After solving (or getting stuck and checking the approach), write the solution from scratch again without looking, to confirm you actually internalized it, not just copied it.
3. Write in `LEARNINGS.md`: For each problem, name the exact data structure that made the optimal solution possible, and why a brute-force approach would have been too slow.

**You're done when:** You've solved all three problems and can re-derive each one from scratch without notes.

---

### Day 21 — Week 2–3 Review + Buffer

**Time:** 3 hrs

**Tasks:**

1. Fix any lingering bugs across all 5 algorithm files. Run `pytest -v` and confirm every test passes.
2. Run `black .` and `ruff check .` to clean up formatting across all algorithm files.
3. Update `README.md` status to "Week 3 — All 5 Algorithms Implemented & Benchmarked (Pure Python)."
4. Update `LEARNINGS.md` with a week summary: what was the hardest algorithm to implement correctly, and why?
5. Commit and push everything.

**You're done when:** Your repo is clean, all tests pass, and `BENCHMARKS.md` has a complete Round 1 comparison table.

---

## WEEK 4 — FastAPI Middleware Layer I (Days 22–27)

> **Goal:** Wrap your algorithms in a real HTTP API that other services could actually plug into.

---

### Day 22 — FastAPI App Skeleton

**Time:** 3 hrs

**Tasks:**

1. Install FastAPI and Uvicorn:

```bash
pip install fastapi "uvicorn[standard]"
```

2. Create `src/api/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="RateFortress", version="0.1.0")

@app.get("/")
def root():
    return {"status": "ok", "service": "RateFortress"}

@app.get("/api/test")
def test_endpoint():
    return {"message": "This endpoint will be rate limited soon."}
```

3. Run it:

```bash
uvicorn src.api.main:app --reload --port 8000
```

4. Confirm `http://localhost:8000/api/test` responds in your browser or with `curl`.

**You're done when:** The FastAPI app runs locally and responds to both routes.

**Write in LEARNINGS.md:** What is an ASGI server, and why does FastAPI need Uvicorn to actually run?

---

### Day 23 — Build Rate Limiting Middleware

**Time:** 4 hrs

**What you're building:** The glue layer that applies any of your 5 algorithms to every incoming request.

**Tasks:**

1. Create `src/middleware/rate_limit_middleware.py`:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter):
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next):
        user_id = request.client.host  # IP-based for now, API keys come Day 26

        if not self.limiter.is_allowed(user_id):
            return JSONResponse(
                status_code=429,
                content={"error": "rate limit exceeded"},
            )

        response = await call_next(request)
        return response
```

2. Wire it into `main.py` using your Token Bucket from Day 17 as the default algorithm.
3. Test it by hammering `/api/test` with a loop of `curl` calls and watching it start returning 429s.

**You're done when:** You can trigger a real HTTP 429 response by exceeding the limit.

---

### Day 24 — HTTP 429 + Retry-After Headers

**Time:** 3 hrs

**What you're doing:** Matching the professional pattern used by Stripe/GitHub/OpenAI from Day 5's research.

**Tasks:**

1. Update the middleware to return proper rate-limit headers on every response, not just 429s:

```python
response.headers["X-RateLimit-Limit"] = str(self.limiter.limit)
response.headers["X-RateLimit-Remaining"] = str(max(0, self.limiter.limit - current_count))
response.headers["Retry-After"] = str(retry_seconds)
```

2. You'll need to expose a `remaining(user_id)` and `retry_after(user_id)` method on each algorithm class — add these now to Token Bucket and Fixed Window Counter at minimum.
3. Test with `curl -i` to confirm headers appear correctly on both success and 429 responses.

**You're done when:** Every response — allowed or blocked — includes correct `X-RateLimit-*` and `Retry-After` headers.

**Write in LEARNINGS.md:** Why do well-designed APIs send rate limit headers on EVERY response, not just when you get blocked?

---

### Day 25 — Per-User / Per-IP / Per-Endpoint Config

**Time:** 4 hrs

**What you're building:** Making the rate limiter configurable instead of hardcoded to one global rule.

**Tasks:**

1. Design a config structure:

```python
RATE_LIMIT_CONFIG = {
    "default": {"limit": 100, "window": 60, "algorithm": "token_bucket"},
    "/api/expensive-endpoint": {"limit": 10, "window": 60, "algorithm": "sliding_window_log"},
}
```

2. Update the middleware to look up the config by `request.url.path`, falling back to `"default"` if no specific rule exists.
3. Add a `scope` option: `per_ip` (current default) vs `per_user` (requires auth, placeholder for now — real API keys arrive Day 26).
4. Test with two different endpoints having two different limits and confirm each enforces independently.

**You're done when:** Two endpoints with two different configured limits both enforce correctly and independently.

---

### Day 26 — API Key Based Identity

**Time:** 3–4 hrs

**What you're building:** Real per-user identity instead of just IP address, so different accounts get different limits.

**Tasks:**

1. Add a simple API key header check: `X-API-Key`. For now, maintain a small in-memory dict mapping API keys to tiers:

```python
API_KEYS = {
    "key_free_abc": {"tier": "free", "limit_multiplier": 1},
    "key_paid_xyz": {"tier": "paid", "limit_multiplier": 10},
}
```

2. Update the middleware: if `X-API-Key` is present and valid, use it as the `user_id` and apply the tier's `limit_multiplier` to the configured limit. If missing, fall back to IP-based limiting with the default (lowest) limit.
3. Test both paths: a request with a valid paid key should get a much higher effective limit than an anonymous IP-based request.

**You're done when:** A request with a paid API key is allowed far more requests than an anonymous request, verified with `curl`.

**Write in LEARNINGS.md:** Why would a real API never put the full API key in a URL query string, but always in a header instead?

---

### Day 27 — DSA Practice Day: Hashing & Design Problems

**Time:** 3–4 hrs

**What you're doing:** Reinforcing the hashmap-heavy design patterns you just used for config lookup and API-key identity.

**Tasks:**

1. Solve on LeetCode (or equivalent), timing yourself:
   - "LRU Cache" (medium) — directly relevant: you'll eventually want to cap how many user entries your in-memory structures hold.
   - "Insert Delete GetRandom O(1)" (medium) — hashmap + array trick for O(1) everything.
   - "Design Twitter" (medium) — a composite design problem combining hashmaps and heaps, similar in spirit to your tiered priority queue coming up next week.
2. Re-derive at least one solution from scratch after solving it, without looking at your own notes.
3. Write in `LEARNINGS.md`: How would an LRU cache be useful INSIDE RateFortress itself, if you had millions of distinct users and limited memory?

**You're done when:** All three are solved and you can explain the O(1) trick behind "Insert Delete GetRandom" from memory.

---

## WEEK 5 — FastAPI Middleware Layer II — Tiering, Resilience & Load Prep (Days 28–33)

> **Goal:** Finish the middleware layer with priority handling, endpoint matching, and graceful failure handling, then do your first manual load test.

---

### Day 28 — Tiered Rate Limits with Priority Queues

**Time:** 4 hrs

**What you're building:** When the system is under heavy load, paid-tier requests should be processed before free-tier ones.

**Tasks:**

1. Add a `PriorityRequestQueue` using `heapq` from your Week 0 Day 4 refresher:

```python
import heapq
import itertools

class PriorityRequestQueue:
    def __init__(self):
        self.heap = []
        self.counter = itertools.count()  # tie-breaker for equal priorities

    def push(self, priority: int, request_id: str):
        heapq.heappush(self.heap, (priority, next(self.counter), request_id))

    def pop(self):
        if self.heap:
            return heapq.heappop(self.heap)
        return None
```

2. Wire this in conceptually as a queuing layer in front of the middleware for a simulated "overload" scenario — write a small script that pushes 50 free-tier and 50 paid-tier requests in random order, then pops them all and confirms paid-tier requests come out first.
3. Write in `LEARNINGS.md`: Where would this priority queue actually sit in a real production system — in the API process itself, or in a separate load balancer/gateway layer? Why does that matter?

**You're done when:** Your test script proves paid-tier requests are dequeued before free-tier ones, even when pushed in mixed order.

---

### Day 29 — Trie for Endpoint Prefix Matching

**Time:** 4 hrs

**What you're building:** Efficient endpoint-pattern matching so a rule like `/api/admin/*` applies to every nested admin route without listing each one.

**Tasks:**

1. Implement a minimal trie for path segments:

```python
class TrieNode:
    def __init__(self):
        self.children = {}
        self.rule = None

class EndpointTrie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, path: str, rule: dict):
        node = self.root
        for segment in path.strip("/").split("/"):
            node = node.children.setdefault(segment, TrieNode())
        node.rule = rule

    def match(self, path: str):
        node = self.root
        best_rule = None
        for segment in path.strip("/").split("/"):
            if segment in node.children:
                node = node.children[segment]
                if node.rule:
                    best_rule = node.rule
            else:
                break
        return best_rule
```

2. Write tests confirming `/api/admin/users` and `/api/admin/settings` both correctly inherit a rule registered at `/api/admin`.
3. Wire this trie into your middleware's config lookup from Day 25, replacing the simple dict lookup.

**You're done when:** A single rule registered at a parent path correctly applies to all its nested child paths.

**Write in LEARNINGS.md:** Why is a trie faster than checking every registered rule with string matching when you have hundreds of endpoint rules?

---

### Day 30 — Integration Tests for Middleware

**Time:** 3–4 hrs

**Tasks:**

1. Install `httpx` for async test client support:

```bash
pip install httpx pytest-asyncio
```

2. Write `tests/test_middleware_integration.py` covering: default limit enforcement, per-endpoint override via trie, API-key-based tiering, and correct headers on both success and 429 responses.
3. Run the full suite and fix anything that breaks.

**You're done when:** All integration tests pass against the real FastAPI app (not just unit tests of the algorithm classes).

---

### Day 31 — Manual Load Test with curl/Postman

**Time:** 3 hrs

**What you're doing:** Your first taste of hammering the API before you bring in proper load testing tools next month.

**Tasks:**

1. Write a simple bash loop to blast requests and visually confirm throttling kicks in:

```bash
for i in {1..30}; do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/test
done
```

2. Try the same with Postman's Runner feature if you prefer a GUI — set it to fire 30 requests in a short burst and inspect the response codes/headers in the results table.
3. Document what you observe in `BENCHMARKS.md`: at what request number did you start seeing 429s? Does it match your configured limit?

**You're done when:** You've watched your own rate limiter block you in real time, and the blocking point matches your configured limit exactly.

---

### Day 32 — Circuit Breaker Pattern Day

**Time:** 4 hrs

**What you're learning:** A core production-resilience pattern that goes beyond rate limiting itself — what should happen if your storage backend (Redis, arriving next week) goes down? A good system degrades gracefully instead of crashing or hanging.

**Tasks:**

1. Read a short explainer on the circuit breaker pattern: **Closed** (normal operation, requests pass through), **Open** (backend is failing, requests fail fast or bypass the check entirely), **Half-Open** (periodically test if the backend has recovered).
2. Implement a minimal circuit breaker wrapping any backend call:

```python
import time

class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.state = "closed"
        self.opened_at = None

    def call(self, func, *args, fallback=True, **kwargs):
        if self.state == "open":
            if time.time() - self.opened_at > self.recovery_timeout:
                self.state = "half_open"
            else:
                return fallback  # fail open: allow the request rather than hang

        try:
            result = func(*args, **kwargs)
            if self.state == "half_open":
                self.state = "closed"
                self.failures = 0
            return result
        except Exception:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.state = "open"
                self.opened_at = time.time()
            return fallback
```

3. Decide and document your policy: should RateFortress **fail open** (allow all requests through if Redis is down — prioritizes availability) or **fail closed** (block all requests — prioritizes strict limit enforcement)? Justify your choice in `docs/`.
4. Write a test that simulates a backend raising exceptions repeatedly, confirms the breaker trips to "open," then confirms it recovers to "closed" after the timeout with a successful call.

**You're done when:** Your circuit breaker correctly trips open after repeated failures and recovers after the timeout, verified by a test.

**Write in LEARNINGS.md:** Which failure policy did you choose (fail open vs fail closed) for a rate limiter specifically, and why is that answer different for, say, a payments authorization service?

---

### Day 33 — Week 4–5 Review + Buffer

**Time:** 3 hrs

**Tasks:**

1. Fix any remaining bugs in the middleware, trie, priority queue, or circuit breaker.
2. Run `black .`, `ruff check .`, and the full `pytest -v` suite.
3. Update `README.md`: "Week 5 — FastAPI Middleware Layer Complete (tiering, endpoint matching, API keys, circuit breaker)."
4. Update `LEARNINGS.md` with a week summary.
5. Commit and push.

**You're done when:** Your middleware layer is fully tested, documented, and committed.

---

## WEEK 6 — Redis Backend I (Days 34–39)

> **Goal:** Make your rate limiter distributed — so it works correctly even when your API runs across multiple server instances.

---

### Day 34 — Redis + Docker Setup

**Time:** 3 hrs

**What you're learning:** Why in-memory state (what you've built so far) breaks the moment you run more than one server instance.

**Tasks:**

1. Install Docker Desktop if you don't have it already.
2. Run Redis locally:

```bash
docker run -d --name ratefortress-redis -p 6379:6379 redis
```

3. Install the Python Redis client and confirm connectivity:

```bash
pip install redis
```

```python
import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)
r.set("test_key", "hello")
print(r.get("test_key"))  # should print "hello"
```

4. Write in `LEARNINGS.md`: Explain in your own words why two separate FastAPI processes, each with their own in-memory `defaultdict` counters, would let a user bypass your rate limit by hitting whichever instance has "spare" capacity.

**You're done when:** You can set and get a key in Redis from Python.

---

### Day 35 — Migrate Fixed Window to Redis (INCR/EXPIRE)

**Time:** 4 hrs

**What you're building:** Your first Redis-backed algorithm, using Redis's atomic `INCR` command.

**Tasks:**

1. Create `src/algorithms/redis_fixed_window.py`:

```python
import time
import redis

class RedisFixedWindow:
    def __init__(self, redis_client: redis.Redis, limit: int, window_seconds: int):
        self.r = redis_client
        self.limit = limit
        self.window_seconds = window_seconds

    def is_allowed(self, user_id: str) -> bool:
        current_window = int(time.time() // self.window_seconds)
        key = f"fixed_window:{user_id}:{current_window}"

        count = self.r.incr(key)
        if count == 1:
            # first request in this window — set expiry so old windows clean themselves up
            self.r.expire(key, self.window_seconds)

        return count <= self.limit
```

2. Why this is atomic: `INCR` on Redis is a single atomic operation server-side — two processes incrementing the same key at the same instant can never both read "4" and both write "5" (the race condition that would happen with a non-atomic read-modify-write in plain Python).
3. Write a test that runs two `RedisFixedWindow` instances (simulating two app servers) pointed at the same Redis, and confirms they share state correctly.

**You're done when:** Two separate Python objects, both backed by the same Redis instance, correctly share the same counter.

**Write in LEARNINGS.md:** What specifically would go wrong if you used `GET` then `SET` instead of `INCR` here?

---

### Day 36 — Migrate Sliding Window Counter to Redis

**Time:** 4 hrs

**Tasks:**

1. Create `src/algorithms/redis_sliding_window_counter.py`, applying the same pattern from Day 35: store `current` and `previous` window counts as separate Redis keys, with `INCR` + `EXPIRE`, and replicate the weighting math from Day 16 in Python (the math itself doesn't need to live in Redis — only the counters do).
2. Write tests mirroring Day 35's "two instances share state" test.
3. Benchmark this Redis-backed version against its pure-Python counterpart from Day 16 — expect it to be SLOWER (network round-trip to Redis) but now correct across multiple instances. Record both numbers in `BENCHMARKS.md`.

**You're done when:** Tests pass and you have a documented throughput comparison: pure Python vs Redis-backed.

**Write in LEARNINGS.md:** Why is "slower but correct across instances" an acceptable tradeoff for a production system?

---

### Day 37 — Sliding Window Log via Redis Sorted Sets

**Time:** 4 hrs

**What you're building:** Using Redis's sorted set (`ZSET`) data structure — a perfect match for timestamp-based sliding window logic.

**Tasks:**

1. Create `src/algorithms/redis_sliding_window_log.py`:

```python
import time
import redis

class RedisSlidingWindowLog:
    def __init__(self, redis_client: redis.Redis, limit: int, window_seconds: int):
        self.r = redis_client
        self.limit = limit
        self.window_seconds = window_seconds

    def is_allowed(self, user_id: str) -> bool:
        key = f"sliding_log:{user_id}"
        now = time.time()
        window_start = now - self.window_seconds

        pipe = self.r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)  # drop old entries
        pipe.zcard(key)                              # count remaining
        pipe.execute()

        current_count = self.r.zcard(key)
        if current_count < self.limit:
            self.r.zadd(key, {str(now): now})
            self.r.expire(key, self.window_seconds)
            return True
        return False
```

2. Write in `LEARNINGS.md`: Why is a sorted set (score = timestamp) a near-perfect data structure match for this algorithm, compared to storing a plain Redis list?

**You're done when:** Tests confirm the Redis-backed sliding window log behaves identically to your pure-Python version from Day 13.

> **Note for later:** the `zcard` check and the `zadd` write above happen as two SEPARATE calls to Redis, not one atomic unit — unlike the Lua-scripted algorithms you'll build on Day 40. Keep this implementation as-is for now; Day 42 is specifically designed to help you find out, under real concurrency, why that's a problem.

---

### Day 38 — Test Redis-Backed Algorithms

**Time:** 3 hrs

**Tasks:**

1. Write a consolidated `tests/test_redis_algorithms.py` covering all three Redis-backed implementations so far (Fixed Window, Sliding Window Counter, Sliding Window Log).
2. Add a `conftest.py` pytest fixture that spins up a fresh Redis test database (use DB index 1, separate from your dev data in DB 0) and flushes it before each test.
3. Run the full suite — pure Python tests AND Redis tests — and confirm everything passes together.

**You're done when:** `pytest -v` passes cleanly across all pure-Python and Redis-backed algorithm tests.

**Write in LEARNINGS.md:** Why is it important to use a separate Redis database index for tests instead of your dev Redis data?

---

### Day 39 — DSA Practice Day: Tries & String Matching

**Time:** 3–4 hrs

**What you're doing:** Reinforcing the trie structure from Week 5 with standalone practice, plus related string-matching problems that come up constantly in interviews.

**Tasks:**

1. Solve on LeetCode (or equivalent):
   - "Implement Trie (Prefix Tree)" (medium) — build one completely from scratch, independent of your endpoint-matching version.
   - "Add and Search Word — Data Structure Design" (medium) — trie with wildcard matching.
   - "Longest Common Prefix" (easy) — can be solved trie-based or more simply; do both approaches and compare.
2. Re-derive the trie implementation from scratch once more without looking at Day 29's code.
3. Write in `LEARNINGS.md`: What's the time complexity of trie insert/search in terms of the key length, and why is that often better than a hashmap for prefix-based lookups specifically?

**You're done when:** You've solved all three and can implement a trie from a blank file without reference.

---

## WEEK 7 — Redis Backend II — Lua Scripts, Atomicity & Eviction (Days 40–45)

> **Goal:** Handle the two trickiest algorithms (Token Bucket, Leaky Bucket) on Redis with true atomicity, prove the system works across multiple app instances, and understand how Redis manages memory at scale.

---

### Day 40 — Token Bucket via Redis + Lua Scripts

**Time:** 4–5 hrs

**What you're learning:** Why `INCR`/`EXPIRE` alone aren't enough here — Token Bucket needs multiple reads and writes (current tokens, last refill time) to happen as ONE atomic unit, which Lua scripting on Redis guarantees.

**Tasks:**

1. Create `src/algorithms/redis_token_bucket.lua`:

```lua
-- KEYS[1] = bucket key, ARGV[1] = capacity, ARGV[2] = refill_rate, ARGV[3] = now
local bucket = redis.call("HMGET", KEYS[1], "tokens", "last_refill")
local tokens = tonumber(bucket[1]) or tonumber(ARGV[1])
local last_refill = tonumber(bucket[2]) or tonumber(ARGV[3])

local elapsed = tonumber(ARGV[3]) - last_refill
local refill = elapsed * tonumber(ARGV[2])
tokens = math.min(tonumber(ARGV[1]), tokens + refill)

local allowed = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
end

redis.call("HMSET", KEYS[1], "tokens", tokens, "last_refill", ARGV[3])
redis.call("EXPIRE", KEYS[1], 3600)
return allowed
```

2. Load and call it from Python:

```python
import redis, time

r = redis.Redis(decode_responses=True)
script = r.register_script(open("src/algorithms/redis_token_bucket.lua").read())

def is_allowed(user_id, capacity=10, refill_rate=1):
    result = script(keys=[f"token_bucket:{user_id}"], args=[capacity, refill_rate, time.time()])
    return bool(int(result))
```

3. Write in `LEARNINGS.md`: Why does Redis guarantee a Lua script runs atomically (no other client's commands can interleave mid-script), and why does that matter for Token Bucket specifically?

**You're done when:** Your Lua-scripted Token Bucket passes the same burst + refill test you wrote in pure Python on Day 17.

---

### Day 41 — Leaky Bucket via Redis + Lua Scripts

**Time:** 4 hrs

**Tasks:**

1. Write an equivalent Lua script for Leaky Bucket (`redis_leaky_bucket.lua`), tracking queue size and last-leak time in a Redis hash, mirroring the logic from your pure-Python version on Day 18.
2. Write the Python wrapper, mirroring Day 40's pattern.
3. Re-run your Day 18 "Token Bucket bursts, Leaky Bucket doesn't" comparison test — this time against the Redis-backed Lua versions — and confirm the same behavioral difference holds.

**You're done when:** The burst-vs-no-burst behavioral contrast is confirmed on the Redis-backed versions too.

---

### Day 42 — Atomicity Deep Dive & Race Condition Testing

**Time:** 4–5 hrs

**What you're doing:** Deliberately trying to BREAK your own rate limiter with concurrent requests, to prove atomicity actually holds — including finding a real bug this plan deliberately left in from Day 37.

**Tasks:**

1. Write a stress test using Python's `concurrent.futures.ThreadPoolExecutor` (or `asyncio.gather`) to fire 50 simultaneous requests for the same user against your Redis-backed Fixed Window limiter, with `limit=10`.
2. Assert that EXACTLY 10 are allowed and 40 are blocked — no more, no less, even under true concurrency. If you see 11 or 12 allowed, you have a race condition to fix.
3. Repeat the same concurrency test against your Lua-scripted Token Bucket.
4. Now repeat it a third time against your **Day 37 Sliding Window Log**. Look closely at the code: `zcard` (the check) and `zadd` (the write) are two SEPARATE calls to Redis, not one atomic unit — unlike Token Bucket's single Lua script. Under 50 concurrent requests with `limit=10`, you should see MORE than 10 allowed. This is a real bug, not a hypothetical one.
5. Fix it the same way you fixed Token Bucket on Day 40: write `redis_sliding_window_log.lua`, combining the cleanup (`ZREMRANGEBYSCORE`), the count check (`ZCARD`), and the conditional write (`ZADD`) into ONE Lua script, so Redis runs all three as a single atomic unit with no gap a second request could slip through.

```lua
-- KEYS[1] = sorted set key, ARGV[1] = limit, ARGV[2] = window_seconds, ARGV[3] = now
redis.call("ZREMRANGEBYSCORE", KEYS[1], 0, tonumber(ARGV[3]) - tonumber(ARGV[2]))
local count = redis.call("ZCARD", KEYS[1])

if count < tonumber(ARGV[1]) then
    redis.call("ZADD", KEYS[1], ARGV[3], ARGV[3])
    redis.call("EXPIRE", KEYS[1], tonumber(ARGV[2]))
    return 1
end
return 0
```

6. Re-run your concurrency test against the new Lua-scripted version and confirm the allowed count is now EXACTLY 10, every time.

**You're done when:** All three Redis-backed algorithms — Fixed Window, Token Bucket, and now Sliding Window Log — allow EXACTLY the configured limit under concurrent load, with no exceptions across repeated runs.

**Write in LEARNINGS.md:** Walk through the exact interleaving of two concurrent requests that let Day 37's original version over-admit past the limit — which Redis call from request A happened before which call from request B?

---

### Day 43 — Distributed Test — Two App Instances, Shared State

**Time:** 4 hrs

**What you're doing:** The moment this project becomes genuinely "distributed" — proving two separate running servers share rate-limit state correctly.

**Tasks:**

1. Run two instances of your FastAPI app on different ports, both pointed at the same Redis:

```bash
uvicorn src.api.main:app --port 8000 &
uvicorn src.api.main:app --port 8001 &
```

2. Write a script that sends requests alternating between `localhost:8000` and `localhost:8001`, all under the same API key/user, with `limit=10`.
3. Confirm the 11th request total (regardless of which port it hit) gets blocked — proving the limit is enforced GLOBALLY across instances, not per-instance.

**You're done when:** The combined request count across both ports respects a single shared limit.

**Write in LEARNINGS.md:** Before Redis, if you'd deployed two instances with your Week 2 pure-Python algorithms, what would have actually happened to the effective rate limit? (Hint: it roughly doubles per instance.)

---

### Day 44 — Key Eviction & TTL Strategy Day

**Time:** 3 hrs

**What you're learning:** How Redis manages memory at scale, and why your rate-limit keys need a deliberate TTL strategy or they'll grow unbounded.

**Tasks:**

1. Read about Redis `maxmemory-policy` options: `noeviction`, `allkeys-lru`, `volatile-lru`, `allkeys-lfu`, `volatile-ttl`. Understand what "volatile" means here (only applies to keys that have a TTL set).
2. Audit every Redis key your algorithms create so far — confirm every single one has an `EXPIRE` set (an unbounded key per user, multiplied across millions of users, is a real memory leak in production).
3. Configure a local Redis container with a small `maxmemory` limit and `allkeys-lru` eviction, then flood it with more unique user keys than it can hold. Observe older keys getting evicted via `redis-cli INFO memory` and `redis-cli --scan`.
4. Write in `LEARNINGS.md`: Why would `volatile-lru` be a safer default than `allkeys-lru` for a system where SOME keys (like config data) should never be evicted, while rate-limit keys can be?

**You're done when:** You've confirmed every rate-limit key type in your codebase has a TTL, and you've watched eviction happen live under a memory cap.

---

### Day 45 — Week 6–7 Review + Buffer

**Time:** 3 hrs

**Tasks:**

1. Fix any remaining race conditions, eviction gaps, or bugs found this week.
2. Run the full test suite, `black .`, and `ruff check .`.
3. Update `README.md`: "Week 7 — Distributed Redis Backend Complete (all 5 algorithms, atomic Lua scripts, verified across multiple instances, TTL-safe)."
4. Update `LEARNINGS.md` with a week summary.
5. Commit and push.

**You're done when:** All 5 algorithms work correctly, atomically, and distributedly — fully tested, memory-safe, and documented.

---

## WEEK 8 — Load Testing with Locust (Days 46–51)

> **Goal:** Get real performance numbers under simulated production traffic — this is what makes your resume bullets credible.

---

### Day 46 — Locust Setup & First Load Test

**Time:** 3 hrs

**Tasks:**

1. Install Locust:

```bash
pip install locust
```

2. Create `loadtests/locustfile.py`:

```python
from locust import HttpUser, task, between

class RateFortressUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def hit_test_endpoint(self):
        self.client.get("/api/test", headers={"X-API-Key": "key_free_abc"})
```

3. Run it with the web UI:

```bash
locust -f loadtests/locustfile.py --host http://localhost:8000
```

4. Open `http://localhost:8089`, start with 10 users, and watch the live stats.

**You're done when:** You've run your first Locust test and seen live requests-per-second and response-time charts.

**Write in LEARNINGS.md:** What's the difference between Locust's "spawn rate" and "number of users"? Why do both matter?

---

### Day 47 — Simulate 100 Concurrent Users

**Time:** 3 hrs

**Tasks:**

1. Run Locust headless at 100 concurrent users:

```bash
locust -f loadtests/locustfile.py --host http://localhost:8000 --headless -u 100 -r 10 --run-time 2m
```

2. Record: total requests, failure rate, median/p95 response time, requests per second.
3. Save the output CSV (`--csv=results_100users`) and commit it under `loadtests/results/`.

**You're done when:** You have a saved CSV of 100-user load test results.

---

### Day 48 — Simulate 500 Concurrent Users

**Time:** 4 hrs

**What you're learning:** Every Redis call you've written since Week 6 has used the SYNCHRONOUS `redis` client, inside an ASYNC FastAPI app. At low load that's invisible. At 500 concurrent users, it becomes the actual bottleneck — worth catching here, before you blame Redis itself.

**Tasks:**

1. Repeat Day 47 at 500 users: `-u 500 -r 50`.
2. Watch specifically for whether your Redis connection pool becomes a bottleneck — check `redis.Redis(connection_pool=...)` settings if you see connection errors, and increase the pool size if needed.
3. Now look at what's actually happening under the hood: a synchronous `redis.Redis` call BLOCKS the entire async event loop while it waits on the network — no other request can be handled by that worker during that wait, which defeats half the point of using FastAPI's async model in the first place. Confirm this by watching your p95 latency climb disproportionately as concurrency increases, even while Redis itself (checked via `redis-cli --latency`) stays fast.
4. Migrate your Redis client calls to `redis.asyncio` (`import redis.asyncio as redis`) and `await` each call (`await r.incr(key)`, etc.) instead of calling synchronously. Your Lua script calls via `register_script` also have an async equivalent — confirm it in the `redis-py` docs.
5. Re-run the same 500-user test and compare p95 latency before and after the migration.

**You're done when:** You have results as `results_500users.csv` from BOTH the sync and async Redis client versions, with a measured latency difference between them, not just a theoretical one.

**Write in LEARNINGS.md:** In your own words, what does "blocking the event loop" actually mean, and why doesn't a bigger connection pool alone fix it?

---

### Day 49 — Simulate 1000 Concurrent Users + Stress Test

**Time:** 4 hrs

**Tasks:**

1. Repeat at 1000 users: `-u 1000 -r 100`.
2. Push further: keep increasing load until you find the breaking point — the user count where failure rate crosses 5% or p95 latency exceeds 1 second. This is your system's actual capacity ceiling.
3. Save results as `results_1000users.csv` and document the breaking point.

**You're done when:** You know the exact user count where your system starts degrading, with numbers to back it up.

**Write in LEARNINGS.md:** What was the bottleneck at your breaking point — was it the rate limiter itself, Redis, or FastAPI/Uvicorn's own request handling?

---

### Day 50 — Document Latency (p50/p95/p99) & Error Rates

**Time:** 3 hrs

**Tasks:**

1. Create `BENCHMARKS.md` section "Load Test Results" with a table across all four runs (10, 100, 500, 1000 users) showing: throughput (req/s), p50, p95, p99 latency, and error rate.
2. Render this as a quick chart (matplotlib, or even just a markdown table) — this table is one of your strongest resume-bullet sources.
3. Commit all CSVs and the updated benchmark doc.

**You're done when:** `BENCHMARKS.md` has a complete, professional-looking load test results table.

---

### Day 51 — DSA Practice Day: Queues & Concurrency Problems

**Time:** 3–4 hrs

**What you're doing:** Reinforcing the queue-based and concurrency-adjacent thinking you've been using all week under load.

**Tasks:**

1. Solve on LeetCode (or equivalent):
   - "Design Circular Queue" (medium) — array-based ring buffer, same idea you studied conceptually in Week 0.
   - "Design Bounded Blocking Queue" (medium) — producer-consumer pattern, directly relevant to how real request queues work under backpressure.
   - "Number of Recent Calls" (easy) — literally a sliding-window-log-style problem in disguise.
2. Write in `LEARNINGS.md`: How does a "bounded blocking queue" relate to what happens to incoming requests when your API is at its breaking point from Day 49 — what should happen to the request that doesn't fit?

**You're done when:** All three are solved and you can connect the "Bounded Blocking Queue" problem directly to your own load test findings.

---

## WEEK 9 — Load Testing II (k6), Spike & Soak Testing (Days 52–56)

> **Goal:** Validate your Locust findings with a second, industry-standard tool, then test the two traffic patterns steady-state load testing misses entirely.

---

### Day 52 — k6 Setup & Comparison Test

**Time:** 3–4 hrs

**Tasks:**

1. Install k6 (via your OS package manager or the k6 website installer).
2. Create `loadtests/k6_test.js`:

```javascript
import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "30s", target: 100 },
    { duration: "1m", target: 500 },
    { duration: "30s", target: 0 },
  ],
};

export default function () {
  const res = http.get("http://localhost:8000/api/test", {
    headers: { "X-API-Key": "key_free_abc" },
  });
  check(res, {
    "status is 200 or 429": (r) => r.status === 200 || r.status === 429,
  });
  sleep(0.2);
}
```

3. Run it: `k6 run loadtests/k6_test.js`.

**You're done when:** k6 completes a full run and prints its summary stats.

---

### Day 53 — Locust vs k6 — Compare Results

**Time:** 3 hrs

**Tasks:**

1. Run the equivalent load profile (100→500 ramping users) in both Locust and k6.
2. Compare their reported p95 latency and throughput — they should be close but rarely identical (different load generation engines).
3. Document any meaningful discrepancy and your hypothesis for why it exists (e.g., k6 is written in Go and can generate load more efficiently than Python's Locust at very high user counts).

**You're done when:** You have a documented comparison between the two tools' results for the same scenario.

**Write in LEARNINGS.md:** If you only had time to use one load testing tool in a real job, which would you pick, and why?

---

### Day 54 — Spike Testing

**Time:** 3 hrs

**What you're learning:** Steady ramp-ups (what you've done so far) don't reveal how your system handles SUDDEN bursts — a very different, very real production scenario (a post goes viral, a client's cron job fires 10,000 requests at once).

**Tasks:**

1. Write a k6 spike-test config that jumps instantly rather than ramping:

```javascript
export const options = {
  stages: [
    { duration: "10s", target: 10 }, // baseline
    { duration: "5s", target: 2000 }, // sudden spike
    { duration: "30s", target: 2000 }, // hold
    { duration: "10s", target: 10 }, // drop back to baseline
  ],
};
```

2. Run it and specifically watch: does your system recover cleanly once the spike ends, or do errors/latency stay elevated afterward (a sign of a resource leak or a queue that never drained)?
3. Document the recovery behavior in `BENCHMARKS.md`.

**You're done when:** You've recorded whether your system returns to baseline latency within a reasonable time after a spike ends.

**Write in LEARNINGS.md:** Why might a system handle a GRADUAL ramp to 2000 users fine but fail under an INSTANT spike to the same 2000 users?

---

### Day 55 — Soak Testing

**Time:** 3–4 hrs

**What you're learning:** Short load tests (minutes) can hide slow memory leaks or connection leaks that only show up over sustained time.

**Tasks:**

1. Run a moderate, sustained load test for an extended duration — at least 45–60 minutes at a modest 100–200 users:

```bash
locust -f loadtests/locustfile.py --host http://localhost:8000 --headless -u 150 -r 10 --run-time 60m --csv=soak_test
```

2. While it runs, periodically check your app process's memory usage (`docker stats` if containerized, or your OS's process monitor) and your Redis memory usage (`redis-cli INFO memory`) every 10 minutes. Plot these over time.
3. Confirm memory stays flat/bounded rather than climbing steadily — a steady upward climb is a leak (check your TTLs from Day 44 if you see one).

**You're done when:** You have a recorded memory-over-time trend showing your system is stable under sustained load, or you've found and fixed a leak.

**Write in LEARNINGS.md:** What's a soak test designed to catch that a 2-minute load test never would?

---

### Day 56 — Finalize Benchmark Report

**Time:** 3 hrs

**Tasks:**

1. Consolidate everything from Weeks 2, 3, 8, and 9 into a single polished `BENCHMARKS.md`: pure-Python algorithm comparison, Redis-backed comparison, steady-state load test results from both tools, plus your spike and soak test findings.
2. Write a short "Key Findings" section at the top summarizing the 4–5 most important takeaways in plain English — this is what you'll paraphrase into resume bullets later.
3. Commit and push.

**You're done when:** `BENCHMARKS.md` reads like a real engineering report, not a scratch file.

---

## WEEK 10 — Observability: Prometheus (Days 57–61)

> **Goal:** Make your system's behavior visible — production systems are blind without metrics.

---

### Day 57 — Prometheus Fundamentals

**Time:** 2–3 hrs

**What you're learning:** What Prometheus actually is before wiring it in.

**Tasks:**

1. Read a short explainer on Prometheus's model: it "scrapes" (pulls) metrics from your app at an HTTP endpoint on a schedule, rather than your app pushing metrics to it.
2. Understand the three metric types you'll use: **Counter** (only goes up — total requests), **Gauge** (goes up/down — current active connections), **Histogram** (buckets of values — request latency distribution).
3. Write in `LEARNINGS.md`: Why does Prometheus "pull" metrics instead of your app "pushing" them? What failure mode does pulling avoid?

**You're done when:** You can explain Counter vs Gauge vs Histogram with a concrete example of each from your own project.

---

### Day 58 — Instrument FastAPI with prometheus-client

**Time:** 4 hrs

**Tasks:**

1. Install the client library:

```bash
pip install prometheus-client
```

2. Add a metrics endpoint to `main.py`:

```python
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "ratefortress_requests_total", "Total requests", ["endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "ratefortress_request_latency_seconds", "Request latency", ["endpoint"]
)

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

3. Hit `/api/test` a few times, then open `/metrics` in your browser and confirm raw Prometheus-format metrics appear.

**You're done when:** `/metrics` returns real metric data after you've generated some traffic.

---

### Day 59 — Track Request/Block Counters Per User/Algorithm

**Time:** 4 hrs

**Tasks:**

1. Instrument the middleware itself (not just the endpoints) to increment `REQUEST_COUNT` with labels for `status="allowed"` vs `status="blocked"`, and which algorithm handled the request.
2. Add a `BLOCKED_REQUESTS` counter broken down by tier (`free` vs `paid`) so you can later see which tier is hitting limits most.
3. Re-run a quick Locust test from Week 8 and confirm the counters increment correctly and match the request totals Locust itself reports.

**You're done when:** Your `/metrics` counters match Locust's own reported totals within a small margin.

**Write in LEARNINGS.md:** Why do labels (like `status` and `algorithm`) matter on a Prometheus counter instead of just creating a separate counter per combination?

---

### Day 60 — Run Prometheus Locally via Docker

**Time:** 3 hrs

**Tasks:**

1. Create `monitoring/prometheus.yml`:

```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: "ratefortress"
    static_configs:
      - targets: ["host.docker.internal:8000"]
```

2. Run Prometheus pointed at this config:

```bash
docker run -d --name prometheus -p 9090:9090 \
  -v "$(pwd)/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml" \
  prom/prometheus
```

3. Open `http://localhost:9090`, go to "Targets," and confirm your `ratefortress` job shows as "UP."

**You're done when:** Prometheus shows your app as a healthy, actively-scraped target.

---

### Day 61 — Query Metrics with PromQL

**Time:** 3 hrs

**Tasks:**

1. In the Prometheus UI's "Graph" tab, try these queries and understand what each shows:

```
rate(ratefortress_requests_total[1m])
sum(rate(ratefortress_requests_total{status="blocked"}[1m])) by (algorithm)
histogram_quantile(0.95, rate(ratefortress_request_latency_seconds_bucket[5m]))
```

2. Write in `LEARNINGS.md`: In your own words, what does `rate(...[1m])` compute on a Counter metric, and why can't you just read the raw counter value to know "requests per second"?

**You're done when:** You can write a PromQL query from scratch to answer "what's my blocked-request rate for paid-tier users over the last 5 minutes?"

---

## WEEK 11 — Observability: Grafana, Logs & Tracing (Days 62–66)

> **Goal:** Turn raw metrics into a live, shareable dashboard, then round out observability with logs and distributed tracing — the "three pillars" of observability, complete.

---

### Day 62 — Grafana Setup via Docker Compose

**Time:** 3 hrs

**Tasks:**

1. Create `docker-compose.yml` at your project root, wiring together your app, Redis, Prometheus, and Grafana as a single stack (you'll keep adding to this file in later weeks):

```yaml
version: "3.8"
services:
  redis:
    image: redis
    ports: ["6379:6379"]
  prometheus:
    image: prom/prometheus
    ports: ["9090:9090"]
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
  grafana:
    image: grafana/grafana
    ports: ["3000:3000"]
```

2. Run the whole stack: `docker-compose up -d`.
3. Open `http://localhost:3000` (default login `admin`/`admin`), add Prometheus as a data source pointing to `http://prometheus:9090`.

**You're done when:** Grafana is running and successfully connected to your Prometheus data source.

---

### Day 63 — Build Live Dashboard Panels

**Time:** 4 hrs

**Tasks:**

1. Create a new dashboard with at least four panels:
   - Requests per second (allowed vs blocked, stacked)
   - p95 latency over time
   - Blocked requests by tier (free vs paid)
   - Top 10 users by request volume
2. Generate live traffic with a quick Locust run while watching the dashboard update in real time.
3. Export the dashboard JSON and commit it under `monitoring/grafana_dashboard.json` so anyone who clones your repo can import the exact same dashboard.

**You're done when:** You have a 4-panel live dashboard, and a screen recording or screenshot of it updating under real load.

**Write in LEARNINGS.md:** Which panel would a paid customer of your API actually want to see if you exposed a status page to them?

---

### Day 64 — Log Aggregation with Loki

**Time:** 3–4 hrs

**What you're learning:** Metrics tell you THAT something is wrong (blocked requests spiked); logs tell you WHY (which specific requests, what error). Loki is Grafana's log aggregation system, designed to pair naturally with the dashboard you just built.

**Tasks:**

1. Add Loki and Promtail to your `docker-compose.yml`:

```yaml
loki:
  image: grafana/loki
  ports: ["3100:3100"]
promtail:
  image: grafana/promtail
  volumes:
    - ./monitoring/promtail.yml:/etc/promtail/config.yml
    - /var/log:/var/log
```

2. Configure your FastAPI app to emit structured JSON logs (using Python's `logging` module with a JSON formatter) instead of plain text — this makes logs queryable by field (user_id, algorithm, status) rather than just full-text search.
3. Add Loki as a second data source in Grafana, and write a LogQL query to find all blocked requests for a specific user in the last 10 minutes.

**You're done when:** You can filter your live logs inside Grafana by a specific field (e.g., `user_id="u1"`) rather than grep-ing raw text.

**Write in LEARNINGS.md:** Why does structured (JSON) logging matter so much more once you have a log aggregation system, compared to when you were just reading logs from a single terminal?

---

### Day 65 — Distributed Tracing with OpenTelemetry

**Time:** 4–6 hrs (OpenTelemetry's setup has a real learning curve the first time — budget the extra hours rather than feeling behind if it eats the full afternoon)

**What you're learning:** The third pillar of observability — tracing shows you the full path and timing of a SINGLE request as it flows through your system (middleware → algorithm → Redis call), which is invaluable once you have more than one service.

**Tasks:**

1. Install the OpenTelemetry FastAPI instrumentation:

```bash
pip install opentelemetry-instrumentation-fastapi opentelemetry-exporter-otlp
```

2. Auto-instrument your app with a few lines:

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
FastAPIInstrumentor.instrument_app(app)
```

3. Add a manual custom span around your Redis Lua script calls specifically, so you can see exactly how much of each request's total latency is spent waiting on Redis vs your own Python logic:

```python
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("redis_token_bucket_call"):
    result = script(keys=[...], args=[...])
```

4. Run a few requests and view the resulting trace (console exporter is fine for local dev — a full Jaeger/Tempo UI is optional here).

**You're done when:** You can see, for a single request, exactly how many milliseconds were spent in your middleware vs. in the Redis call.

**Write in LEARNINGS.md:** Metrics, logs, and traces are often called the "three pillars of observability." In one sentence each, what question does each pillar answer that the other two can't?

---

### Day 66 — Alerting Rules + Review

**Time:** 3 hrs

**Tasks:**

1. Add one Grafana alert rule: notify (even just log it) if the blocked-request rate for paid-tier users exceeds a threshold — that would signal your limits might be misconfigured for your best customers.
2. Review the whole observability stack: confirm `docker-compose up -d` brings up a fully working app + Redis + Prometheus + Grafana + Loki setup from a clean clone of your repo.
3. Update `README.md`: "Week 11 — Full Observability Stack Complete (Prometheus + Grafana + Loki + OpenTelemetry tracing, live dashboard, alerting)."
4. Commit and push.

**You're done when:** A fresh clone of your repo can run `docker-compose up -d` and get a working, fully observable system with zero manual configuration.

---

## WEEK 12 — Algorithm Comparison Engine (Days 67–71)

> **Goal:** Build the feature that proves you understand tradeoffs, not just implementation — this is your project's "wow factor."

---

### Day 67 — Design the /compare Endpoint

**Time:** 3 hrs

**Tasks:**

1. Design the endpoint contract: `GET /compare?users=100&requests_per_user=50&window=10` should run the SAME synthetic traffic pattern through all 5 algorithms and return a structured comparison.
2. Sketch the response schema first, before coding:

```json
{
  "scenario": { "users": 100, "requests_per_user": 50, "window_seconds": 10 },
  "results": [
    {
      "algorithm": "fixed_window",
      "allowed": 420,
      "blocked": 80,
      "avg_latency_ms": 0.02
    },
    {
      "algorithm": "token_bucket",
      "allowed": 460,
      "blocked": 40,
      "avg_latency_ms": 0.03
    }
  ]
}
```

3. Write in `LEARNINGS.md`: Why design the response schema BEFORE writing the endpoint logic?

**You're done when:** Your response schema is written down and makes sense on its own, before any code exists.

---

### Day 68 — Build the Comparison Report Generator

**Time:** 4 hrs

**Tasks:**

1. Create `src/api/compare.py` implementing the endpoint from Day 67: generate the same synthetic request pattern, run it through all 5 pure-Python algorithm instances (reuse your Week 2–3 classes directly — no need to hit real Redis for this comparison tool), and return the structured JSON.
2. Wire it into `main.py` as `GET /compare`.
3. Test it manually with a few different `users`/`requests_per_user`/`window` combinations and sanity-check the results make sense (e.g., Leaky Bucket should generally block the most under bursty synthetic traffic).

**You're done when:** `/compare` returns a correct, structured JSON comparison for any input scenario you throw at it.

---

### Day 69 — Document Tradeoffs (Accuracy/Memory/Performance/Fairness)

**Time:** 3–4 hrs

**Tasks:**

1. Add a `tradeoffs` section to the `/compare` response for each algorithm — this is qualitative, written by you, not computed: accuracy (does it have the boundary-burst problem?), memory (O(1) per user vs O(requests) per user), performance (from your benchmarks), and fairness (does it treat a bursty user differently from a steady one?).
2. Write this once, carefully, in `docs/tradeoffs.md`, then have `/compare` pull from this static reference rather than hardcoding text in the endpoint.
3. Write in `LEARNINGS.md`: In one sentence per algorithm, what's the single scenario where THIS algorithm is clearly the best choice?

**You're done when:** `/compare`'s response includes genuinely useful, well-reasoned tradeoff text for each algorithm.

---

### Day 70 — Fairness Simulation Day

**Time:** 4 hrs

**What you're learning:** "Performs well on average" and "treats users fairly" are NOT the same claim — this day tests the fairness dimension directly with deliberately skewed traffic, instead of just the uniform synthetic traffic you've used so far.

**Tasks:**

1. Extend your synthetic traffic generator to support non-uniform patterns: a small number of "bursty" users who send all their requests in a tight cluster, alongside many "steady" users who space their requests evenly — same total request count for both user types.
2. Run this skewed scenario through all 5 algorithms and compare: does a bursty user get blocked more or less often than a steady user who sent the exact same NUMBER of requests, just spread out? (Token Bucket should notably favor the bursty user up to its capacity; Leaky Bucket should penalize them hardest.)
3. Add these findings as a new `fairness` field in your `/compare` response and in `docs/tradeoffs.md`.

**You're done when:** You have concrete, measured evidence (not just theory) of which algorithms favor bursty vs steady users, using your own skewed-traffic generator.

**Write in LEARNINGS.md:** If your API's business model depends on predictable, fair usage across all customers, which algorithm would you now avoid, based on today's actual measurements rather than just the Week 0 theory?

---

### Day 71 — Polish Comparison Engine Output (JSON + HTML)

**Time:** 3 hrs

**Tasks:**

1. Add an `Accept`-header-aware response: if the client requests `text/html`, render a simple comparison table page instead of raw JSON (use Jinja2 templates, which FastAPI supports natively).
2. Make the HTML version genuinely presentable — a clean table with the 5 algorithms as rows and allowed/blocked/latency/tradeoffs/fairness as columns. This is the feature you'll screen-record for your demo video later.
3. Commit and push.

**You're done when:** Visiting `/compare` in a browser (not just via `curl`) renders a clean, readable comparison table.

---

## WEEK 13 — Dockerization & Cloud Deployment (Days 72–76)

> **Goal:** Ship it — a live, public URL is worth far more than a project that only runs on your machine.

---

### Day 72 — Dockerize the FastAPI App

**Time:** 3–4 hrs

**Tasks:**

1. Create a `Dockerfile` at the project root:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

2. Build and run it locally:

```bash
docker build -t ratefortress .
docker run -p 8000:8000 ratefortress
```

3. Confirm `/api/test` and `/compare` both work from the containerized app.

**You're done when:** Your app runs correctly entirely inside a Docker container, with no dependency on your local Python environment.

---

### Day 73 — Docker Compose for Full Stack

**Time:** 3 hrs

**Tasks:**

1. Extend your `docker-compose.yml` from Week 11 to include your own app as a service (not just Redis/Prometheus/Grafana/Loki):

```yaml
app:
  build: .
  ports: ["8000:8000"]
  depends_on: [redis]
  environment:
    - REDIS_HOST=redis
```

2. Update your Redis connection code to read `REDIS_HOST` from an environment variable (defaulting to `localhost` for local dev without Docker).
3. Run `docker-compose up --build` and confirm the entire stack — app, Redis, Prometheus, Grafana, Loki — comes up together with one command.

**You're done when:** One command (`docker-compose up --build`) brings up your entire working system from scratch.

**Write in LEARNINGS.md:** Why is reading `REDIS_HOST` from an environment variable better than hardcoding `localhost` in your code?

---

### Day 74 — Choose & Set Up Cloud Host

**Time:** 3 hrs

**Tasks:**

1. Pick a host for your public deployment — Render and Railway both offer straightforward Docker-based free/cheap tiers that work well for a portfolio project; AWS EC2 gives you more control but more setup. Pick whichever fits your timeline and budget.
2. Create an account and a new service/instance, connecting it to your GitHub repo.
3. Write in `LEARNINGS.md`: What did you choose, and what was the single deciding factor (cost, ease of setup, or resume value of "deployed on AWS" specifically)?

**You're done when:** You have a cloud account set up and connected to your GitHub repo, ready to deploy.

---

### Day 75 — Deploy & Configure Secrets/Env Vars

**Time:** 4 hrs

**Tasks:**

1. Configure your host to build from your `Dockerfile` (or `docker-compose.yml`, depending on platform support).
2. Set environment variables/secrets on the platform (Redis connection string if using a managed Redis add-on, any API keys).
3. Trigger your first deploy and watch the build logs. Fix any issues that only show up in the cloud environment (common ones: missing env vars, wrong port binding, Redis host mismatch).

**You're done when:** Your app is live at a public URL and `/api/test` responds correctly over the internet.

---

### Day 76 — Smoke Test the Live Deployment

**Time:** 3 hrs

**Tasks:**

1. Run a scaled-down Locust test (Week 8's script) against your PUBLIC url instead of localhost, at a modest user count your free/cheap tier can handle — be mindful of your host's rate/usage limits.
2. Confirm `/metrics`, `/compare`, and the core rate-limited endpoint all work correctly in production.
3. Share the live link with a friend and watch them hit it from a completely different network — confirm per-IP limiting still behaves correctly for a genuinely different IP.

**You're done when:** Your live deployment has been tested by a real person on a real, different network.

---

## WEEK 14 — CI/CD, Blue-Green Deploys & Rollback (Days 77–81)

> **Goal:** Automate testing and deployment so every push is verified and shipped without manual steps — and know exactly what to do when a bad deploy ships anyway.

---

### Day 77 — GitHub Actions: Run Tests on Push

**Time:** 3 hrs

**Tasks:**

1. Create `.github/workflows/test.yml`:

```yaml
name: Run Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest -v
```

2. Push a small change and confirm the Actions tab shows your test suite running automatically.
3. Fix any CI-specific failures (common one: tests assuming `localhost` Redis when CI needs `redis` as the service hostname).

**You're done when:** A green checkmark appears automatically on your latest commit after pushing.

**Write in LEARNINGS.md:** Why run tests against a Redis _service container_ in CI rather than mocking Redis entirely?

---

### Day 78 — GitHub Actions: Auto-Deploy on Merge

**Time:** 3–4 hrs

**Tasks:**

1. Depending on your Week 13 host: most platforms (Render, Railway) auto-deploy on push to `main` with zero extra GitHub Actions config needed — confirm this is enabled in your host's dashboard.
2. If deploying to EC2 manually, add a second workflow job that SSHs in and pulls the latest image after tests pass — only trigger this job if the test job succeeded (`needs: test`).
3. Make a trivial change, push to `main`, and confirm it automatically appears on your live URL without you touching the deploy process by hand.

**You're done when:** A push to `main` results in your live site updating automatically, with no manual deploy step.

---

### Day 79 — Blue-Green Deployment Day

**Time:** 4 hrs

**What you're learning:** How to deploy a new version with ZERO downtime and an instant rollback path, instead of just overwriting the running version in place.

**Tasks:**

1. Read the blue-green deployment concept: run two identical environments ("blue" = currently live, "green" = new version). Deploy and fully test the new version on "green" while "blue" still serves all live traffic, then switch a router/load-balancer to point at "green" only once it's verified healthy.
2. Simulate this locally: run two containers of your app on different ports (mimicking blue/green), put a simple reverse proxy (nginx, or even just manually switching which port a test script hits) in front, and practice "switching" traffic from one to the other.
3. If your Week 13 host supports it natively (Render and Railway both have zero-downtime deploy features built in), read their docs on how their deploy mechanism actually achieves this, and confirm it matches the blue-green concept.

**You're done when:** You can explain, with your own local simulation as a concrete reference, exactly how a traffic switch from blue to green happens with zero dropped requests.

**Write in LEARNINGS.md:** Why is blue-green deployment specifically valuable for a RATE LIMITER — what would happen to in-flight rate-limit counters if you did a hard restart instead?

---

### Day 80 — Rollback Strategy & Incident Drill Day

**Time:** 3–4 hrs

**What you're doing:** Practicing the thing nobody wants to need: rolling back a bad deploy, under simulated time pressure.

**Tasks:**

1. Tag your current known-good version in Git: `git tag v-stable-1`.
2. Deliberately introduce a bug (e.g., break the Token Bucket refill math) and "deploy" it (to your local blue-green setup from Day 79, or your real host if you're comfortable).
3. Run a timed drill: starting from noticing the bug (via your Day 66 alerting or a failing smoke test), how fast can you identify the bad commit, roll back to `v-stable-1`, and confirm the system is healthy again? Time yourself.
4. Write a short `docs/runbook.md`: the exact steps to roll back, in order, so future-you (or a teammate) doesn't have to figure it out under pressure during a real incident.

**You're done when:** You've completed a full rollback drill from a known bad state back to healthy, with a written runbook to show for it.

**Write in LEARNINGS.md:** What was the single slowest part of your rollback drill, and what would you change about your setup to make that faster next time?

---

### Day 81 — CI/CD Review + Badge in README

**Time:** 2 hrs

**Tasks:**

1. Add a GitHub Actions status badge to the top of your `README.md`:

```markdown
![Tests](https://github.com/your-username/ratefortress/actions/workflows/test.yml/badge.svg)
```

2. Review the whole pipeline end to end one more time: push a deliberately failing test, confirm CI catches it and blocks (or at least clearly flags) the deploy, then fix it.
3. Commit and push.

**You're done when:** Your README shows a live, accurate passing/failing test badge.

---

## WEEK 15 — Documentation, Demo, Interview Prep & Resume Bullet (Days 82–86)

> **Goal:** Package everything you built into something a recruiter can understand in 60 seconds — and make sure YOU can defend every claim out loud.

---

### Day 82 — Architecture Diagram

**Time:** 2–3 hrs

**Tasks:**

1. Go to draw.io (or Excalidraw) and draw the full system:

```
Client Request
     ↓
[FastAPI + RateLimit Middleware] — Circuit Breaker wraps Redis calls
     ↓
[Endpoint Trie — matches config rule]
     ↓
[Selected Algorithm: Fixed/Sliding/Token/Leaky]
     ↓
[Redis — atomic state, Lua scripts, TTL-bounded]
     ↓
Allowed → Response (200) + X-RateLimit headers
Blocked → Response (429) + Retry-After

Alongside: Prometheus scrapes /metrics → Grafana dashboard
           App logs → Loki (structured, queryable)
           OpenTelemetry traces → per-request timing breakdown
```

2. Export as PNG and save it to `docs/architecture.png`.

**You're done when:** Your architecture diagram is saved and clearly shows every major component you built.

---

### Day 83 — Write the README

**Time:** 4 hrs

**Tasks:**

1. Write a README a recruiter can understand in 60 seconds:

```markdown
# RateFortress

![Tests](badge_link) | [Live Demo](your_deployed_url) | [Benchmarks](BENCHMARKS.md)

> A distributed rate limiting engine implementing 5 algorithms from scratch,
> benchmarked under load, observable via Prometheus/Grafana/Loki, and deployed publicly.

## What It Does

- Implements Fixed Window, Sliding Window Log, Sliding Window Counter, Token Bucket, and Leaky Bucket — from first principles
- Distributed via Redis with Lua-scripted atomic operations, verified race-condition-free under concurrent load
- Exposed as pluggable FastAPI middleware with per-user/per-IP/per-endpoint config, API-key tiering, and a circuit breaker for graceful Redis-outage handling
- Load tested with Locust and k6 up to 1000+ concurrent users, including spike and soak testing
- Fully observable: Prometheus metrics, Loki logs, OpenTelemetry tracing, live Grafana dashboard
- CI/CD via GitHub Actions, containerized with Docker, deployed publicly with a documented rollback runbook

## Live Demo

[your deployed URL]

## Architecture

[diagram — see docs/architecture.png]

## Benchmarks

See [BENCHMARKS.md](BENCHMARKS.md) for full algorithm, load, spike, and soak test comparisons.

## Setup

[clear local setup steps — docker-compose up --build]

## Limitations

- Single-region Redis (no cross-region replication)
- Synthetic load tests only (no real production traffic data)
```

2. Make sure every claim in the README is something you can actually back up if asked about it in an interview.

**You're done when:** Someone with zero context can read your README and understand exactly what you built and why it's impressive.

---

### Day 84 — Record Demo Video + LinkedIn Post

**Time:** 3 hrs

**Tasks:**

1. Record a 2–3 minute demo (Loom or similar):
   - 0:00–0:20: "This is RateFortress, a distributed rate limiter I built from scratch." (show architecture diagram)
   - 0:20–1:00: Show `/compare` rendering the live algorithm comparison table
   - 1:00–1:40: Show the Grafana dashboard updating live while you run a quick Locust burst
   - 1:40–2:00: "Deployed publicly, fully tested, CI/CD on every push" (show the live URL + green test badge)
2. Add the video link to your README.
3. Post on LinkedIn with a short write-up: what you built, the hardest problem you solved (race conditions are a great story here), and a link to the repo.

**You're done when:** Your demo video and LinkedIn post are both live.

---

### Day 85 — Mock Interview Prep Day

**Time:** 3 hrs

**What you're doing:** Practicing explaining this project out loud, under the kind of pressure an actual interview creates — this is the step most people skip, and it's the one that matters most.

**Tasks:**

1. Write out (then practice saying out loud, not just reading) 60-second answers to: "Walk me through this project," "What was the hardest bug you hit?," and "Why did you choose Token Bucket as your default algorithm?"
2. Anticipate and prepare answers for the questions most likely to come up given what you built: "How do you handle a race condition?" (Day 42), "What happens if Redis goes down?" (Day 32's circuit breaker), "How would this scale to 10 Redis nodes?" (Day 4's consistent hashing concept), "What's the tradeoff between Token Bucket and Leaky Bucket?" (Day 18/70).
3. If possible, do a real mock interview — ask a friend, or ask Claude to role-play as an interviewer grilling you on this specific project.

**You're done when:** You can answer all five anticipated questions above out loud, confidently, in under 90 seconds each, without reading from notes.

---

### Day 86 — Final Polish + Resume Bullet

**Time:** 3 hrs

**Tasks:**

1. Go through every file: remove debug prints, dead code, and leftover TODOs.
2. Make sure every module has a short docstring explaining what it does.
3. Write your resume bullet, backed by your actual benchmark numbers from `BENCHMARKS.md`:

```
Built and deployed RateFortress — a distributed rate limiting engine implementing
5 algorithms (Token Bucket, Leaky Bucket, Fixed/Sliding Window) from scratch in
Python, backed by Redis with Lua-scripted atomic operations verified race-condition-
free under concurrent load; exposed as FastAPI middleware with tiered API-key auth
and circuit-breaker resilience, load tested to 1000+ concurrent users (incl. spike/soak)
via Locust/k6, instrumented with Prometheus/Grafana/Loki/OpenTelemetry, and shipped via
Docker + GitHub Actions CI/CD to a public endpoint with a documented rollback runbook.
```

4. Add it to your resume and LinkedIn.

> 🎉 **Core project complete.** You built a genuinely production-grade systems project, grounded in real fundamentals — this is not a small thing. Everything from Week 16 onward is where this project stops looking like a portfolio piece and starts looking like something a real team would ship.

---

## WEEKS 16–20 — Research Layer & Optional Extensions (Days 87–100)

> Optional in the sense that no single day here is required — but this is what turns "I built a project" into "I can think critically about tradeoffs and keep pushing a system further," which is a different, higher tier of signal to recruiters. Pick what interests you most, or do all of it — Weeks 21-29 build directly on top of this layer.

---

### Day 87 — Draft the Comparative Write-Up

**Time:** 3–4 hrs

**Tasks:**

1. Draft a short technical article: "Which Rate Limiting Algorithm Should You Actually Use? A Practical Benchmark." Structure: the problem, the 5 algorithms (briefly), your benchmark methodology, your results, your recommendation per use case.
2. Pull your real numbers from `BENCHMARKS.md` directly — don't estimate, use what you actually measured.

**You're done when:** You have a full first draft, even if rough.

---

### Day 88 — Add Real Numbers & Charts to the Write-Up

**Time:** 3 hrs

**Tasks:**

1. Add 1–2 simple charts (matplotlib or even a clean markdown table) visualizing your throughput and latency comparisons across algorithms, plus your fairness-simulation findings from Day 70.
2. Edit for clarity — read it out loud once, fix anything that doesn't flow.

**You're done when:** The write-up includes real charts/tables backed by your own data, not placeholder text.

---

### Day 89 — Publish on Dev.to/Medium/Portfolio

**Time:** 2–3 hrs

**Tasks:**

1. Publish the write-up on Dev.to, Medium, or your own portfolio site (koi-bito.github.io).
2. Link it from your project's `README.md` and from your LinkedIn post.

**You're done when:** The article is live and linked from your repo.

---

### Day 90 — Share & Gather Feedback

**Time:** 2–3 hrs

**Tasks:**

1. Share your article and/or repo link in one or two relevant communities (e.g., a relevant subreddit, a backend-engineering Discord/Slack you're part of, Hacker News "Show HN" if it genuinely fits their guidelines).
2. Respond to any comments or questions you get — this itself is good practice for defending your technical decisions to strangers.
3. Note any genuinely useful critiques for Day 91.

**You're done when:** You've shared the project publicly at least once and engaged with any resulting feedback.

---

### Day 91 — Write a Follow-Up "Lessons Learned" Post

**Time:** 2–3 hrs

**Tasks:**

1. Incorporate the most interesting feedback from Day 90 into a short follow-up post: "What I got wrong (or hadn't considered) about rate limiting, per the comments."
2. This kind of intellectual honesty — publicly updating your views based on feedback — reads very well to technical recruiters.

**You're done when:** Your follow-up post is written (published is a bonus, but not required).

---

### Day 92 — Optional: Add a 6th Algorithm — GCRA (Generic Cell Rate Algorithm)

**Time:** 4 hrs

**What you're learning:** GCRA is what Stripe actually uses in production (via their open-source `limiters` approach) — a mathematically elegant alternative to Token Bucket that tracks a single "theoretical arrival time" value instead of a token count.

**Tasks:**

1. Read a plain-English explainer on GCRA before touching code.
2. Implement `src/algorithms/gcra.py` following the same `is_allowed(user_id)` interface as your other 5 algorithms, so it drops straight into your existing benchmark harness and `/compare` endpoint.
3. Add it to your comparison report and benchmarks.

**You're done when:** GCRA is a 6th fully working, tested, benchmarked algorithm in your comparison engine.

---

### Day 93 — Optional: Explore Redis Cluster / Sharding Conceptually

**Time:** 3 hrs

**Tasks:**

1. Read about Redis Cluster mode — how it shards keys across multiple nodes using hash slots, tying back to the consistent hashing concept from Week 0 Day 4.
2. If you want hands-on practice, spin up a small local Redis Cluster via Docker Compose (several Redis nodes + cluster setup) and confirm your existing Lua-scripted algorithms still work against it (note: Lua scripts in cluster mode have constraints around multi-key operations — this is worth discovering and documenting).
3. Document in `docs/scaling.md`: what would need to change in RateFortress to run against a real multi-node Redis Cluster in production.

**You're done when:** You have a written plan for scaling RateFortress beyond a single Redis instance, whether or not you fully implement it.

---

### Day 94 — Optional: Add a gRPC Alternative Interface

**Time:** 4 hrs

**What you're learning:** Many high-throughput internal services use gRPC instead of REST — exposing your rate limiter as a gRPC service as well shows you understand more than one API paradigm.

**Tasks:**

1. Define a minimal `.proto` file for a `CheckRateLimit(user_id, endpoint) -> Allowed` RPC.
2. Implement the gRPC server using Python's `grpcio` library, reusing your existing algorithm classes underneath — the business logic doesn't change, only the transport layer does.
3. Write a simple test client and confirm it gets correct allow/block responses.

**You're done when:** You can call your rate limiter over gRPC and get the same correct behavior as the REST version.

**Write in LEARNINGS.md:** Why might an internal microservice-to-microservice call prefer gRPC over REST, while a public-facing API almost always prefers REST?

---

### Day 95 — Optional: Contribute Back — Package Your Middleware

**Time:** 3–4 hrs

**Tasks:**

1. Extract your FastAPI middleware (algorithms + middleware layer, not the full app) into a standalone, installable package structure (`setup.py` or `pyproject.toml`).
2. Write package-level documentation showing how someone else could `pip install` and drop it into their own FastAPI project with just a few lines of config.
3. Optionally, actually publish it to PyPI under a unique name (e.g., `ratefortress-middleware`) — a real published package is a strong, concrete artifact.

**You're done when:** Your middleware can be installed and used in a completely separate test FastAPI project, with documentation someone else could follow.

---

### Day 96 — Optional: Security Hardening Pass

**Time:** 3 hrs

**Tasks:**

1. Audit your own system for security gaps: are your `/metrics` and `/compare` admin-ish endpoints themselves rate limited (an attacker could hammer your comparison engine to burn CPU)? Should they require their own API key?
2. Implement API key rotation: a mechanism to issue a new key for an existing account and invalidate the old one without downtime.
3. Double-check secrets handling end to end: confirm no API keys, Redis passwords, or credentials ever appear in logs, Git history, or client-visible error messages.

**You're done when:** Every endpoint, including your own internal tooling endpoints, is deliberately protected — not just the "main" business endpoint.

---

### Day 97 — Optional: Peer Review

**Time:** 2–3 hrs

**Tasks:**

1. Ask a friend, mentor, or online community member who codes to review your repo — specifically ask them to try to break something or find a confusing part of the README.
2. Incorporate at least one piece of real feedback, and document what you changed and why.

**You're done when:** Someone other than you has read your code and you've acted on at least one piece of their feedback.

---

### Day 98 — Final Codebase Cleanup

**Time:** 2–3 hrs

**Tasks:**

1. Re-run `black .` and `ruff check .` one final time across the entire codebase.
2. Double check `.gitignore` — confirm no secrets, `.env` files, or local Redis dumps were ever committed.
3. Tag a `v1.0.0` release on GitHub.

**You're done when:** Your repo is in a state you'd be comfortable sharing in a job interview without any "oh wait, ignore that part" caveats.

---

### Day 99 — Capstone Walkthrough Recording

**Time:** 2 hrs

**Tasks:**

1. Record a longer (10–15 minute), unedited, more technical walkthrough for your own archive — not the polished 2-minute LinkedIn demo, but you explaining every architectural decision, every tradeoff, and every bug you hit, as if teaching it to a junior engineer.
2. Keep this one private if you like — its value is in forcing you to articulate the whole system end to end one more time, and it becomes a great private reference before a real interview.

**You're done when:** You have a complete, unedited recording of yourself explaining the entire system from memory.

---

### Day 100 — Project Wrap-Up + Retrospective

**Time:** 2 hrs

**Tasks:**

1. Write a final entry in `LEARNINGS.md`: the single hardest technical problem across the whole project, and how you solved it (race conditions in Week 7 are a strong candidate).
2. Write a short list of what you'd do differently if you started over — this is exactly the kind of reflective answer that stands out in interviews.
3. Celebrate — this was a long, genuinely substantial build, start to finish.

**You're done when:** You can walk someone through this entire project, start to finish, from memory, confidently.

---

## WEEK 21 — Adversarial Testing & Abuse Simulation (Days 101–105)

> **Goal:** Close the loop on why you started this project — fake free trials and abuse — by actually trying to break your own rate limiter the way a real attacker would, not just load-testing it politely.

---

### Day 101 — Research Real-World Rate Limit Bypass Techniques

**Time:** 3 hrs

**Tasks:**

1. Research how real abuse actually bypasses naive, IP-based rate limiting: IP rotation via proxy pools, distributed botnets (many real IPs, few requests each), header spoofing (`X-Forwarded-For` manipulation when a server trusts it blindly), and account cycling (creating many free accounts instead of hammering one).
2. Read about why blindly trusting `X-Forwarded-For` without validating it against a known, trusted proxy list is a classic rate-limiter bypass — an attacker can simply set that header to a random new value on every request if your server forwards it unchecked.
3. Write in `LEARNINGS.md`: Which of your current rate-limiting dimensions (IP, API key) is most vulnerable to which bypass technique, and why?

**You're done when:** You can name at least three concrete bypass techniques and which of your current defenses each one would defeat.

---

### Day 102 — Build an Attacker Simulation Script

**Time:** 3–4 hrs

**Tasks:**

1. Create `loadtests/adversary_simulation.py` that fires requests spoofing `X-Forwarded-For` with random values on every request, against a test deployment where you've deliberately NOT yet validated the trusted-proxy chain.
2. Also simulate "account cycling": generate many fake free-tier API keys rapidly and spread requests thin across them instead of hammering one key.
3. Run it against your current system and observe the result honestly.

**You're done when:** You have a working adversary script and a recorded, honest measurement of how much it bypasses.

---

### Day 103 — Test & Fix Your Defenses

**Time:** 3–4 hrs

**Tasks:**

1. Document, with real numbers, exactly how much extra throughput an attacker gained via IP spoofing against your current default config.
2. Fix the `X-Forwarded-For` trust issue: only honor it when the request comes from a known, trusted proxy/load-balancer IP range; otherwise fall back to the raw connecting IP.
3. Re-run your Day 102 adversary script and confirm the bypass no longer works, or is significantly harder.

**You're done when:** Your Day 102 numbers meaningfully improve after the fix, with before/after evidence.

---

### Day 104 — Defense in Depth: Behavioral Signals

**Time:** 4 hrs

**What you're building:** A lightweight heuristic layer on top of your hard limits, since any single threshold-based defense can eventually be tuned around.

**Tasks:**

1. Add a behavioral signal: flag identities whose request timing is suspiciously regular (near-zero variance between requests — a classic script signature) versus human-like jitter.
2. Combine this with new-account age and request volume into a simple composite risk score. Don't hard-block on this alone — use it to automatically apply a stricter limit tier and log it for review.
3. Write in `LEARNINGS.md`: Why is "apply a stricter limit and flag for review" usually the better response to a suspicious signal than "block instantly"?

**You're done when:** A scripted, perfectly-regular request pattern gets automatically bumped to a stricter tier, while normal jittery human-like traffic does not.

---

### Day 105 — Red Team Report

**Time:** 3 hrs

**Tasks:**

1. Write `docs/redteam_report.md`: every bypass technique you tried, whether it worked, what you fixed, and what residual risk remains. Be honest — no app-level rate limiter is bulletproof; note what you'd still want a WAF/CDN layer (like Cloudflare) to catch.
2. Add a line to your README pointing to this report — it's a genuinely rare, impressive artifact that demonstrates adversarial thinking, not just implementation.

**You're done when:** `docs/redteam_report.md` is a complete, honest account of your own system's attack surface.

**Write in LEARNINGS.md:** This is the exact problem you started this project to solve. Has your understanding of "fake free trials" as a problem changed since Day 1?

---

## WEEK 22 — System Design Interview Mastery (Days 106–110)

> **Goal:** "Design a rate limiter" is one of the most commonly asked system design interview questions at major tech companies. Translate everything you built into fluent, whiteboard-level interview performance.

---

### Day 106 — Capacity Planning & Back-of-Envelope Math

**Time:** 3 hrs

**Tasks:**

1. Practice the estimation math real system design interviews expect: if your API serves 1 million requests/second globally with 10 million active users, estimate Redis memory needed (~100 bytes of state per user), estimate network bandwidth to Redis, and estimate how many Redis instances you'd need under a safe per-node memory threshold.
2. Do the same estimate for Sliding Window Log (much higher memory per user, since it stores a timestamp per request) versus Token Bucket (near-constant memory per user) — this makes the algorithm-choice tradeoff concrete at scale, not just theoretical.
3. Write your math, with work shown, in `docs/capacity_planning.md`.

**You're done when:** You can produce a rough memory/node estimate for 1M req/sec from memory, showing your work.

---

### Day 107 — Mock System Design Interview #1

**Time:** 2 hrs (timed)

**Tasks:**

1. Set a 45-minute timer. Prompt: "Design a rate limiter for a public API." No code — whiteboard/Excalidraw only. Walk through: requirements clarification, algorithm choice with tradeoffs, storage choice, how it scales, how it fails gracefully.
2. Record yourself (audio is enough) talking through it as if a real interviewer were in the room.
3. Listen back: where did you hesitate? What did you forget to mention that you actually built (the circuit breaker, the TTL eviction strategy)?

**You're done when:** You've completed one full timed mock interview and identified at least two concrete gaps in your delivery.

---

### Day 108 — Mock System Design Interview #2

**Time:** 2 hrs (timed)

**Tasks:**

1. Harder prompt, 45 minutes: "Design a rate limiter that works correctly across multiple regions, where users might hit a US server and an EU server interchangeably." This pushes past what you've built (single-region Redis) into genuinely harder territory — cross-region replication lag, eventual consistency, and whether strict global accuracy is even worth the latency cost.
2. It's completely fine not to have a perfect answer — the skill being practiced is reasoning out loud about an unsolved problem, exactly what real interviews test.
3. Write in `LEARNINGS.md`: What approach did you land on, and what explicit tradeoff did you accept?

**You're done when:** You've reasoned through a problem harder than what you actually built, out loud, and can state your tradeoff clearly.

---

### Day 109 — Write a Formal RFC / Architecture Decision Record

**Time:** 3–4 hrs

**Tasks:**

1. Write `docs/ADR-001-algorithm-choice.md` in the real-world Architecture Decision Record format: Context, Decision, Alternatives Considered, Consequences.
2. Write it for your "Token Bucket as default" decision specifically, referencing your actual Day 19/70 benchmark and fairness data as evidence — as if proposing this to a real team.
3. This single document is one of the most senior-looking artifacts in your repo — most junior candidates never produce one.

**You're done when:** `docs/ADR-001-algorithm-choice.md` reads like something a real engineering team would actually find in their repo.

---

### Day 110 — Review & Refine

**Time:** 2–3 hrs

**Tasks:**

1. Re-do ONE of your Day 107/108 mock interviews, applying what you learned from listening back the first time.
2. Update your Day 85 interview-prep notes with anything new you want to remember.

**You're done when:** Your second attempt is noticeably more fluent than your first, and you can point to exactly what improved.

---

## WEEK 23 — Multi-Tenant Admin Dashboard (Days 111–115)

> **Goal:** Give RateFortress a real face — an admin dashboard most backend-only portfolio projects never bother building, which makes yours noticeably more complete.

---

### Day 111 — Design the Admin API

**Time:** 3 hrs

**Tasks:**

1. Design admin-only REST endpoints: `GET /admin/keys` (list all keys + tier + current usage), `POST /admin/keys` (issue a new key), `PATCH /admin/keys/{key}` (change tier/limit), `GET /admin/keys/{key}/usage` (usage history).
2. Protect all of these behind a separate, more sensitive admin credential — never reuse a regular API key for admin auth.
3. Implement the endpoints in FastAPI, backed by your existing API key structure.

**You're done when:** All four admin endpoints work and are protected by admin-only auth, verified with a non-admin key correctly getting rejected.

---

### Day 112 — Persist API Keys Properly

**Time:** 3–4 hrs

**Tasks:**

1. Move your API key store from the in-memory dict (Week 4) into Redis hashes, or a lightweight SQLite/Postgres table if you'd rather practice real SQL — admin changes need to survive a restart.
2. Migrate your middleware's key-lookup logic to read from this persistent store.
3. Write a seed script that populates a few test keys, so your repo is demo-ready out of the box.

**You're done when:** API keys and their tiers survive an app restart.

---

### Day 113 — Build the Dashboard Frontend (Part 1)

**Time:** 4 hrs

**Tasks:**

1. Scaffold a minimal frontend — a single HTML page with vanilla JS/`fetch` calls is genuinely fine here; keep it simple and functional rather than reaching for a full framework unless you specifically want that practice.
2. Build the "list all keys + tier + usage" view, pulling from your Day 111 admin API.
3. Style it minimally but cleanly — this will appear in your demo video.

**You're done when:** The dashboard's list view correctly renders live data from your admin API.

---

### Day 114 — Build the Dashboard Frontend (Part 2)

**Time:** 3–4 hrs

**Tasks:**

1. Add "issue new key" and "change tier" forms, wired to your admin API's POST/PATCH endpoints.
2. Add a simple usage chart per key (even a basic Chart.js bar chart of requests over the last 24 hours is enough).
3. Confirm the full loop end to end: issue a key in the dashboard, use it against your real API, watch its usage count update live.

**You're done when:** You can create a new key in the UI, immediately use it, and watch its usage reflect in the dashboard.

---

### Day 115 — Polish & Secure the Dashboard

**Time:** 3 hrs

**Tasks:**

1. Make sure the dashboard itself is rate limited and its admin auth is solid — don't let your admin panel become the weak point in an otherwise hardened system.
2. Add the dashboard to your Docker Compose stack and update your architecture diagram.
3. Update `README.md` and record a short clip of the dashboard for your demo video update.

**You're done when:** The dashboard is part of your one-command `docker-compose up` stack.

**Write in LEARNINGS.md:** What was harder than expected about connecting a frontend to a backend you'd only ever tested with `curl`/`pytest` before?

---

## WEEK 24 — Usage-Based Billing with Stripe (Days 116–120)

> **Goal:** Close the loop on the original "fake free trials" motivation — the real reason tiered rate limits and API keys exist in a business is to meter and bill usage. Build the actual billing side.

---

### Day 116 — Stripe Metered Billing Fundamentals

**Time:** 3 hrs

**Tasks:**

1. Create a free Stripe account in **test/sandbox mode only** (never touch real payment details for this project) and read their metered billing documentation — how usage records get reported against a subscription, and how Stripe calculates the invoice at period end.
2. Map your existing tiers onto a real Stripe Product + Price with a metered billing model (e.g., "$0.001 per request beyond the free tier's included amount").
3. Write in `LEARNINGS.md`: What's the difference between "licensed" and "metered" billing in Stripe's model, and why does a rate-limited API naturally fit the metered model?

**You're done when:** You have a test-mode Stripe Product/Price configured for metered usage.

---

### Day 117 — Report Usage to Stripe

**Time:** 4–6 hrs (first-time Stripe integration — sandbox setup, SDK quirks, getting the async reporting right — commonly runs long; don't rush it to fit a 4-hour box)

**Tasks:**

1. Install the Stripe Python SDK: `pip install stripe`.
2. After each allowed request from a paid-tier key, asynchronously report a usage record to Stripe's metered billing API — don't do this synchronously in the request's critical path, since billing shouldn't add latency to the actual rate-limit check.
3. Confirm in Stripe's test dashboard that usage records are accumulating correctly for a test customer.

**You're done when:** A burst of test requests shows up as accumulating usage in Stripe's dashboard.

---

### Day 118 — Webhook Handling

**Time:** 3–4 hrs

**Tasks:**

1. Implement a Stripe webhook endpoint to receive events like `invoice.created` and `invoice.payment_failed`.
2. On a payment-failure webhook, automatically downgrade that customer's API key to the free tier (or revoke it) — the real-world consequence loop that makes tiering actually matter to a business.
3. Test this with Stripe's CLI webhook-forwarding tool in your local dev environment.

**You're done when:** A simulated failed payment correctly and automatically downgrades the affected key's tier.

---

### Day 119 — Generate a Simple Invoice View

**Time:** 3 hrs

**Tasks:**

1. Add an endpoint (or a dashboard page, tying back to Week 23) where a customer can see their current billing period's usage and estimated charges, pulled live from Stripe's API.
2. Confirm the numbers shown match what Stripe itself reports in its dashboard.

**You're done when:** Your own invoice view and Stripe's dashboard agree on the numbers.

---

### Day 120 — Document the Billing Flow

**Time:** 2–3 hrs

**Tasks:**

1. Add `docs/billing.md` explaining the full loop: request allowed → usage reported → Stripe aggregates → invoice generated → webhook on payment failure → key downgraded.
2. Update your architecture diagram to include Stripe as an external dependency.
3. Commit and push. Most rate limiters stop at the throttling logic and never touch the business reason it exists — this closes that gap.

**You're done when:** `docs/billing.md` and your diagram both reflect the complete billing loop.

---

## WEEK 25 — Chaos Engineering (Days 121–125)

> **Goal:** Deliberately break things in ways a well-behaved test never would, inspired by Netflix's Chaos Monkey — this is what separates "it works in my tests" from "I know exactly how it fails."

---

### Day 121 — Chaos Engineering Fundamentals

**Time:** 2–3 hrs

**Tasks:**

1. Read about the philosophy of chaos engineering: instead of only testing that a system works under expected conditions, deliberately inject real-world failure modes (crashed dependencies, network latency, resource exhaustion) in a controlled way to find weaknesses before they find you in production.
2. Write down your own failure hypotheses BEFORE testing them: "I believe if Redis dies mid-request, my circuit breaker will trip open within N failed calls." Record these predictions now, so you can check your own intuition against reality on Day 122.

**You're done when:** You have 3–4 written predictions about how your system will fail, before you've tested any of them.

---

### Day 122 — Kill Redis Mid-Load-Test

**Time:** 3–4 hrs

**Tasks:**

1. Start a Locust load test, then mid-run, kill your Redis container: `docker kill ratefortress-redis`.
2. Observe: does your circuit breaker (Week 5) trip as predicted? What's the actual error rate and latency spike during the outage, measured precisely via your Grafana dashboard?
3. Restart Redis and confirm the circuit breaker correctly recovers to "closed" state.

**You're done when:** You have a recorded, measured answer to your Day 121 prediction about this exact scenario.

---

### Day 123 — Inject Network Latency with Toxiproxy

**Time:** 4 hrs

**Tasks:**

1. Install Toxiproxy (a chaos-testing proxy tool) and route your app's Redis connection through it.
2. Inject artificial latency (e.g., 200ms, then 2000ms) on the Redis connection and observe how your p95/p99 latency and your circuit breaker react at each level.
3. Find the latency threshold where your system's behavior meaningfully degrades, and document it.

**You're done when:** You know the exact Redis-latency threshold where your system starts to visibly suffer.

---

### Day 124 — Resource Exhaustion Test

**Time:** 3–4 hrs

**Tasks:**

1. Deliberately starve your app container of resources (`docker run --memory=128m` or similar) and re-run a moderate load test. Does it crash cleanly, degrade gracefully, or hang?
2. Fix anything that fails ungracefully — e.g., add a request timeout if one is missing, so a slow Redis call can't hold a worker thread forever under memory pressure.

**You're done when:** Your system either degrades gracefully under resource starvation, or you've documented and fixed the ungraceful failure you found.

---

### Day 125 — Chaos Engineering Report

**Time:** 2–3 hrs

**Tasks:**

1. Write `docs/chaos_report.md`: every experiment, your Day 121 hypothesis, what actually happened, and what you fixed as a result.
2. Add any newly discovered resilience behaviors to your README's feature list — "chaos-tested resilience" is a genuinely rare, impressive line on a resume.

**You're done when:** `docs/chaos_report.md` honestly documents at least one prediction that turned out wrong, and what you learned from it.

**Write in LEARNINGS.md:** Which of your Day 121 predictions was wrong, and what did that teach you about the limits of reasoning about a system without actually testing it?

---

## WEEK 26 — Polyglot Performance Lab: Go Implementation (Days 126–130)

> **Goal:** Step outside Python entirely to directly compare raw language performance for a concurrency-bound task — a concrete, measured talking point about language tradeoffs beats a resume keyword every time.

---

### Day 126 — Go Fundamentals Refresher

**Time:** 3 hrs

**Tasks:**

1. If you're new to Go, work through the basics: goroutines, channels, and the `sync` package (specifically `sync.Mutex` and `sync/atomic`) — you don't need deep Go expertise, just enough to implement one algorithm correctly and safely under concurrency.
2. Set up a Go project: `go mod init ratefortress-go`.

**You're done when:** You can write and run a trivial concurrent Go program using goroutines and a mutex.

---

### Day 127 — Implement Token Bucket in Go

**Time:** 4 hrs

**Tasks:**

1. Port your Token Bucket algorithm (Week 3, Day 17) to Go, using `sync.Mutex` (or `sync/atomic` for the lock-free version, if you want the extra challenge) to make it safe under concurrent goroutines.
2. Write Go's standard `testing` package tests mirroring your Python tests from Day 17.

**You're done when:** Your Go Token Bucket passes the same burst + refill test logic as your Python version.

---

### Day 128 — Expose It as an HTTP Service

**Time:** 3–4 hrs

**Tasks:**

1. Use Go's standard `net/http` package (no framework needed) to expose the same `/api/test`-style endpoint, with your Go Token Bucket as middleware.
2. Confirm it behaves identically (same allow/block pattern) to your Python/FastAPI version under the same test inputs.

**You're done when:** The Go service and the Python service make identical allow/block decisions on identical input.

---

### Day 129 — Head-to-Head Benchmark

**Time:** 4 hrs

**Tasks:**

1. Run the exact same Locust/k6 load profile (reuse your Week 8–9 scripts) against both the Python/FastAPI version and the new Go version, same hardware, same Redis backend.
2. Record throughput and p95/p99 latency for both, side by side, in `BENCHMARKS.md`.

**You're done when:** You have a real, measured throughput comparison between Python and Go for the identical algorithm and workload.

---

### Day 130 — Document the Tradeoff

**Time:** 2–3 hrs

**Tasks:**

1. Write a short, honest comparison: how much faster was Go, and was it worth the development-time/complexity cost for YOUR use case? (The honest answer is often "Python was fast enough" — that's a mature, defensible conclusion for an interview, not a failure.)
2. This becomes a strong answer to "have you worked with other languages?" backed by real, measured evidence instead of a resume keyword.

**You're done when:** You have a written, numbers-backed opinion on when you would and wouldn't reach for Go over Python for this kind of service.

---

## WEEK 27 — Teaching & Community Content (Days 131–133)

> **Goal:** Teaching something forces a deeper, more durable understanding of it than building alone ever does — and it compounds your public portfolio.

---

### Day 131 — Write a Beginner-Friendly Tutorial

**Time:** 3–4 hrs

**Tasks:**

1. Write "Rate Limiting From Scratch: A Beginner's Guide," explicitly aimed at someone who knows Python but has never built a rate limiter — simpler and more pedagogical than your Day 87 comparative research article.
2. Use your OWN Week 0–3 learning journey as the narrative spine — what confused you at first, and how it clicked.

**You're done when:** You have a complete, genuinely beginner-accessible tutorial, not a condensed version of your technical docs.

---

### Day 132 — Record a Teaching Video

**Time:** 3 hrs

**Tasks:**

1. Record a 10–15 minute screen-recorded walkthrough teaching Token Bucket and Sliding Window Log to an imagined beginner audience, live-coding a simplified version from scratch (not just reading your finished code).
2. Post it publicly (YouTube unlisted or public, or embedded in your Dev.to/Medium article).

**You're done when:** The video is recorded and live-codes the concept rather than narrating finished code.

---

### Day 133 — Engage & Iterate

**Time:** 2 hrs

**Tasks:**

1. Share the tutorial/video in a beginner-friendly community (a learning-to-code subreddit, a Discord study group) where it will genuinely help people, not as a self-promo drop.
2. Respond to any questions — explaining your own project to confused beginners is one of the fastest ways to find the gaps in your own understanding.

**You're done when:** You've shared it somewhere genuinely useful and answered at least one real question about it.

---

## WEEK 28 — Repo Professionalization (Days 134–136)

> **Goal:** The small, often-skipped details that separate "a student's project" from "something a team could actually adopt."

---

### Day 134 — Contribution Guidelines & Templates

**Time:** 2–3 hrs

**Tasks:**

1. Add `CONTRIBUTING.md` (how someone would add a 6th/7th algorithm, following your existing `is_allowed(user_id)` interface pattern), a `LICENSE` file (MIT is a sensible default for a portfolio project), and GitHub issue/PR templates.
2. Add a `CODE_OF_CONDUCT.md` if you intend for this to be genuinely open to outside contributions.

**You're done when:** A stranger reading `CONTRIBUTING.md` would know exactly how to propose a new algorithm to your project.

---

### Day 135 — Project Board & Issue Tracking

**Time:** 2 hrs

**Tasks:**

1. Set up a GitHub Projects board retroactively reflecting your weeks of work as columns/cards — this gives any visitor an instant visual sense of the project's scope and history.
2. File a few genuine "good first issue" tickets for anything you intentionally left unfinished (e.g., GCRA, Redis Cluster, a Rust implementation) — this signals the project is alive and extensible, not a dead snapshot.

**You're done when:** Your GitHub Projects board accurately reflects the real scope of what you built.

---

### Day 136 — Final Repo Pass

**Time:** 2–3 hrs

**Tasks:**

1. Walk through your repo exactly as a first-time visitor would: clone it fresh on a different machine (or a clean VM/container) and follow only your own README, with no prior knowledge. Fix anything that doesn't work from a truly cold start.
2. Commit and push.

**You're done when:** A completely fresh clone, following only your README, works end to end with no undocumented steps.

---

## WEEK 29 — Final Capstone & Retrospective (Days 137–140)

> **Goal:** Close out what is now a genuinely months-long, multi-disciplinary engineering project the right way.

---

### Day 137 — Update All Resume Bullets

**Time:** 2–3 hrs

**Tasks:**

1. Rewrite your Day 86 resume bullet to reflect everything added since: adversarial/red-team testing, system design interview artifacts (ADR, capacity planning), the admin dashboard, Stripe billing integration, chaos engineering, and the Go performance comparison. You'll likely need 2–3 bullets now, or one condensed bullet plus a linked case study.
2. Draft a short "case study" version of this project (half a page) suitable for a portfolio site or to send directly to a recruiter who asks "tell me more about this."

**You're done when:** You have resume bullets that honestly cover the full scope without reading as bloated.

---

### Day 138 — Final Architecture Diagram (v2)

**Time:** 2–3 hrs

**Tasks:**

1. Redraw your Day 82 architecture diagram to include everything added since: admin dashboard, Stripe, chaos-testing notes, the Go service as an alternative implementation path.
2. This diagram alone, shown in an interview, should prompt at least five follow-up questions you're now fully prepared to answer.

**You're done when:** Your v2 diagram accurately represents the complete system as it exists today.

---

### Day 139 — Full System Walkthrough Recording (v2)

**Time:** 2–3 hrs

**Tasks:**

1. Record an updated version of your Day 99 capstone walkthrough, now covering the full system end to end.
2. Compare it to your Day 99 recording if you still have it — notice how much more fluent and complete your explanation is now.

**You're done when:** You have a current, complete recording of yourself explaining the entire system from memory.

---

### Day 140 — The Retrospective

**Time:** 2 hrs

**Tasks:**

1. Write a final, honest `LEARNINGS.md` entry: looking back at Day 1's version of you — who just wanted to swap out CertChain for "something stronger" — what's the single biggest thing that changed about how you think about building software?
2. Write down, specifically, which of these 140 days you're proudest of, and which single skill from this project you expect to use again and again in your career.

**You're done when:** You can honestly say you built something over these months that very few fresh graduates ever attempt at this depth — and you understand every single piece of it.

---

## ADDENDUM — Senior Review Follow-Ups (Days 141–143)

> These three days exist because a senior-developer review of this plan flagged three realistic production concerns the core 140 days don't cover. They're appended here, after Day 140, rather than inserted earlier, specifically so they don't renumber anything you've already been tracking progress against.

---

### Day 141 — Rate Limit by Compound Key

**Time:** 3–4 hrs

**What you're learning:** Every algorithm you've built limits on a SINGLE dimension at a time (an IP, or an API key). Real production rate limiters usually compose several dimensions at once — e.g., "this API key, on this specific endpoint, can't exceed X req/min" AND "this IP, across ALL endpoints, can't exceed Y req/min" — enforced simultaneously, not as alternatives.

**Tasks:**

1. Design a compound key format combining multiple dimensions, e.g. `f"{api_key}:{endpoint}:{ip}"`, and decide which dimensions should be ANDed (all must pass) versus which should stay independent checks.
2. Update your middleware to check multiple compound keys per request — e.g., a per-endpoint-per-key limit AND a global per-IP limit — and reject the request if EITHER is exceeded.
3. Write a test with two users sharing an IP but using different API keys: confirm the per-key limits are independent, while the shared per-IP limit still applies across both.

**You're done when:** A single request is correctly checked against more than one rate-limit dimension at once, with the stricter of the two governing the outcome.

**Write in LEARNINGS.md:** Why would a real API want BOTH a per-key limit and a per-IP limit, instead of just picking the stricter of the two as a single global rule?

---

### Day 142 — Warm-Up & Cold-Start Behavior

**Time:** 3 hrs

**What you're learning:** Redis-held rate-limit state survives an app restart — but anything you keep in local memory (your Day 32 circuit breaker's state, any in-process caches) does NOT. A restarted instance starts "cold" while Redis is still "warm," and that mismatch can cause subtly wrong behavior right after a deploy.

**Tasks:**

1. Audit your codebase for anything held in local memory that assumes continuity across restarts — the circuit breaker's failure count and state are the obvious candidate.
2. Simulate a cold start deliberately: with Redis already holding live rate-limit data from a running test, kill and restart your FastAPI process mid-test. Confirm the circuit breaker correctly resets to "closed" (not stuck "open" from before the restart, and not blind to a backend that was already failing).
3. Decide and document a policy: should a freshly restarted instance assume Redis is healthy until proven otherwise (optimistic), or verify connectivity before serving any traffic (a readiness check)? Implement a `/health/ready` endpoint reflecting this choice.

**You're done when:** You can restart your app mid-test and it recovers to a sane, intentional state — not just whatever its local variables happen to default to.

**Write in LEARNINGS.md:** What's the difference between a liveness check and a readiness check, and which one should gate whether your load balancer sends an instance real traffic?

---

### Day 143 — Graceful Shutdown Handling

**Time:** 3 hrs

**What you're learning:** This directly completes your Day 79 blue-green deployment work — switching traffic to a new "green" instance is only half the story if the old "blue" instance gets killed mid-request instead of being allowed to finish what it's already handling.

**Tasks:**

1. Add a signal handler for `SIGTERM` (the signal Docker/your orchestrator sends before a hard kill) that stops accepting NEW connections immediately, but lets in-flight requests finish within a bounded grace period.
2. Test it directly: start a request that takes a few seconds (add an artificial `asyncio.sleep` to one test endpoint), send `SIGTERM` to the process mid-request, and confirm that specific request still completes successfully while new requests are refused.
3. Tie this back into Day 79: update your blue-green deployment notes to specify the grace period your orchestrator should wait before force-killing the old instance, based on what you measured today.

**You're done when:** An in-flight request survives a `SIGTERM`, and a new request sent during the same shutdown window is correctly rejected rather than silently dropped.

**Write in LEARNINGS.md:** What would a user actually experience if you'd skipped this — what does an ungracefully killed in-flight request look like from the client's side?

---

## Daily Checklist

Use this every single day:

- [ ] Did I commit to GitHub today?
- [ ] Did I write in `LEARNINGS.md`?
- [ ] Did I actually understand what I built, or just copy-paste it?
- [ ] Did I run `pytest -v` before stopping for the day?
- [ ] What will I do first tomorrow?

---

## When You Get Stuck (You Will)

1. **Read the error message carefully** — it usually tells you exactly what's wrong.
2. **Google the exact error message** in quotes.
3. **Check the relevant tool's docs/forum** — FastAPI, Redis, Locust, Prometheus, and Grafana all have active communities; most errors have been hit before.
4. **Check Redis connectivity first** when anything distributed misbehaves: `docker ps`, `redis-cli ping`.
5. **Add a `print()` or log line** at the exact point you suspect is wrong — don't guess, verify.
6. **Isolate the failure** — write a tiny standalone script that reproduces just the broken part, outside the full app.
7. **Ask Claude** — paste the full error message and the exact code that caused it.

---

_Good luck. 140 days from now, you won't just have a project that holds up under hard technical questions — you'll have one that's actually been attacked, billed, broken, and taught to someone else. That's a different kind of done._
