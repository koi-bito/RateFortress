---
title: "Which Rate Limiting Algorithm Should You Actually Use? A 40,000 req/s Benchmark"
published: true
description: "Empirical benchmarks comparing Fixed Window, Sliding Window Log, Sliding Window Counter, Token Bucket, Leaky Bucket, and GCRA in Python and Redis."
tags: python, architecture, redis, performance
series: "Distributed Systems from First Principles"
canonical_url: "https://koi-bito.github.io/posts/rate-limiting-algorithms-benchmark"
---

# Which Rate Limiting Algorithm Should You Actually Use? A 40,000 req/s Benchmark

Every backend engineer eventually implements rate limiting. Most start with a simple Redis GET and INCR.

When traffic surges, three problems emerge:
1. Race conditions: Concurrent requests slip through between checking the counter and incrementing it, admitting twice the allowed quota.
2. Boundary spikes: Users send their full quota at 11:59:59 and another full quota at 12:00:01, hitting the database with double the expected traffic.
3. Event loop stalls: In async Python frameworks like FastAPI, synchronous Redis socket operations block the single event loop thread.

To test these tradeoffs with real numbers, I spent several weeks building RateFortress, a distributed rate limiting engine in Python, Redis, and Lua, tested with Locust and k6.

Here are the concrete findings.

---

## The Contenders at a Glance

I implemented and benchmarked five foundational algorithms plus GCRA:
1. Fixed Window Counter: Counts requests per time window (such as 1 minute). Allows 2x traffic spikes right at the window boundary.
2. Sliding Window Log: Stores an exact timestamp for every request in a deque or Redis Sorted Set. High memory consumption (O(N) timestamps per client).
3. Sliding Window Counter: Blends previous and current window counts to approximate a rolling window. Smooths boundaries with constant O(1) memory.
4. Token Bucket: Holds tokens and refills at a constant rate; requests consume tokens. Allows short, controlled bursts while capping sustained throughput.
5. Leaky Bucket: Requests enter a buffer and leak out at a uniform rate. Eliminates downstream spikes, but completely rejects client bursts.
6. GCRA (Generic Cell Rate Algorithm): Calculates a single Theoretical Arrival Time instead of tracking floating-point tokens.

---

## 1. Pure In-Memory Speed

Using a benchmark harness running 10,000 requests across 100 clients:

```
Algorithm                 Throughput (req/s)   Latency / Check   Per-User Memory
Sliding Window Log        3,471,620 req/s      0.28 µs           O(N) (Timestamps)
Fixed Window Counter      2,819,761 req/s      0.35 µs           O(1) (48 bytes)
Leaky Bucket              2,580,845 req/s      0.38 µs           O(1) (Virtual math)
Sliding Window Counter    2,115,551 req/s      0.47 µs           O(1) (64 bytes)
Token Bucket              2,066,073 req/s      0.48 µs           O(1) (48 bytes)
```

In memory, every algorithm exceeds 2 million operations per second per CPU core. However, in-memory state cannot scale across multiple API containers behind a load balancer.

---

## 2. Distributed Redis: Why Lua Scripting Matters

When moving rate limiting state to Redis 7, network socket I/O becomes the dominant factor:
- Redis Fixed Window (INCR): ~43,300 req/s
- Redis Sliding Window Counter (Lua): ~7,200 req/s
- Redis Token Bucket (Lua): ~6,500 req/s
- Redis Leaky Bucket (Lua): ~6,300 req/s
- Redis Sliding Window Log (Lua): ~5,800 req/s

### The 50-Thread Race Condition Test
When 50 concurrent threads simultaneously claimed quota against a limit of 10:
- Non-atomic Redis pipeline (GET then SET): Admitted 22 requests (120% leak).
- Atomic Lua scripts (EVALSHA): Admitted exactly 10 requests and blocked 40 (0% leak).

Because Redis processes Lua scripts atomically within its single execution loop, token checks, refills, and decrements occur in an isolated step.

---

## 3. The Async Win: Preventing Event-Loop Starvation

Under 500 concurrent simulated users in Locust:
- Synchronous Redis (redis.Redis): Median latency 17.0 ms, throughput 874 req/s.
- Asynchronous Redis (redis.asyncio): Median latency 13.0 ms, throughput 1,080 req/s.

Switching to non-blocking async Redis yielded a 23.5% latency reduction and prevented queue dropouts by keeping Uvicorn's event loop unblocked.

---

## 4. The Decision Cheat Sheet

- Building a Developer API or CLI? Pick Token Bucket or GCRA. Developers fire requests in bursts when loading dashboard widgets, so they should not be penalized for idle intervals.
- Protecting Login or Payment Endpoints? Pick Sliding Window Log. Eliminates boundary gaps completely. The memory cost is small for low-frequency sensitive endpoints.
- Running a High-Volume Public Gateway? Pick Sliding Window Counter. Delivers smooth boundary protection with constant O(1) RAM.
- Fronting a Fragile Legacy Database? Pick Leaky Bucket. Forces incoming bursts into a predictable, constant outflow.

---

## Source Code & Benchmarks

- GitHub Repository: https://github.com/koi-bito/RateFortress
- Full Benchmark Report: https://github.com/koi-bito/RateFortress/blob/main/BENCHMARKS.md
