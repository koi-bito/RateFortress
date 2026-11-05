# Rate Limiting Algorithm Tradeoffs & Evaluation Notes

These are my tradeoff notes across the six rate limiting algorithms implemented in RateFortress.

---

## 1. Tradeoff Summary Table

| Algorithm | Time Complexity | Space Complexity (Per User) | Boundary Burst Vulnerability | Redis Lua Throughput | Fairness Model | Primary Strength | Weakness |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Fixed Window Counter | O(1) | O(1) (1 counter + 1 epoch) | High (2x burst at boundaries) | ~43,300 req/s | Variable (favors boundary alignment) | Minimal compute and memory overhead | Traffic spikes at window transitions |
| Sliding Window Log | O(log N) or O(N) eviction | O(N) (N = request count) | None (exact rolling window) | ~5,850 req/s | Uniform and strict | Absolute precision, zero leakage | Memory consumption explodes under high traffic |
| Sliding Window Counter | O(1) | O(1) (2 counter values) | Negligible (bounded error < 0.05%) | ~7,200 req/s | Balanced and smoothed | Practical sweet spot (accuracy + O(1) RAM) | Slight approximation bias on uneven load |
| Token Bucket | O(1) | O(1) (tokens count + timestamp) | None (governed by capacity and refill) | ~6,530 req/s | Favors bursty clients (accumulates idle credit) | Accommodates natural bursts and batch traffic | Downstream services may receive sudden traffic spikes |
| Leaky Bucket | O(1) | O(1) (virtual queue depth + timestamp) | None (strictly smooth outflow rate) | ~6,310 req/s | Penalizes bursty clients (enforces rigid pacing) | Protects fragile downstream dependencies | Drops valid requests during momentary bursts |
| GCRA | O(1) | O(1) (single TAT timestamp ~32B) | None (governed by burst tolerance tau) | ~6,695 req/s | Favors bursty clients (up to tolerance tau) | Clean math, minimal Redis memory | Harder conceptual model for beginners |

---

## 2. In-Depth Algorithm Notes

### 1. Fixed Window Counter
Fixed Window is the fastest limiter, but I would not use it on sensitive endpoints. If a client sends their full quota at 00:59 and another full quota at 01:01, both pass, delivering double the intended traffic in two seconds. It is only useful for coarse daily limits where memory economy is crucial and temporary spikes will not destabilize downstream systems.

### 2. Sliding Window Log
Sliding Window Log is 100% exact, but I would not use it at scale. Storing every timestamp in a Redis sorted set consumes gigabytes of memory once you hit millions of users. It makes sense only for low-frequency security routes like login, password reset, or payment confirmation where zero leakage is worth the extra RAM.

### 3. Sliding Window Counter
This is my preferred general-purpose algorithm for public APIs. By taking a weighted average of the current and previous window counts, it prevents boundary spikes while storing only two numbers per user. It is an approximation, but the margin of error is tiny in practice.

### 4. Token Bucket
Token Bucket is what I would pick for developer-facing APIs or CLI tools. When users load a dashboard, they naturally fire off 10 or 15 parallel requests, followed by minutes of reading. Token Bucket allows that burst up to bucket capacity without dropping requests, while holding sustained traffic to the refill rate.

### 5. Leaky Bucket
I would use Leaky Bucket specifically when fronting slow or fragile backend systems like batch PDF generation or legacy databases. It forces all traffic into a constant outflow rate. If a user bursts, excess requests are dropped immediately to keep the backend from falling over.

### 6. GCRA (Generic Cell Rate Algorithm)
GCRA gives the same burst-tolerant rate shaping as Token Bucket, but tracks only a single timestamp (the Theoretical Arrival Time) in Redis. I like it because it stores less state than Token Bucket while executing slightly faster in Redis Lua scripts.

---

## 3. Fairness Simulation Notes

When I tested non-uniform traffic with 80% steady users and 20% bursty users:
1. Token Bucket had the highest admission rate for bursty users because idle credit covers the initial spike.
2. Leaky Bucket had the highest drop rate for bursty users because it forces a constant outflow rate.
3. Fixed Window Counter produced unpredictable results depending on whether the burst landed across a reset boundary.
4. Sliding Window Counter gave the most equitable treatment across steady and bursty clients without storing timestamp arrays.
