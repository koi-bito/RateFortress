# Community Showcase & Technical Defense Notes

These are my notes for sharing RateFortress on developer communities like Hacker News and Reddit, along with answers to technical questions.

---

## 1. Hacker News Post Draft

Title: Show HN: RateFortress – Distributed rate limiting engine with 6 algorithms benchmarked

Body:
I spent the past few months building RateFortress, a distributed rate limiting engine in Python and Redis designed to explore the practical tradeoffs between rate limiting algorithms with real numbers.

GitHub: https://github.com/koi-bito/RateFortress
Benchmark Report: https://github.com/koi-bito/RateFortress/blob/main/BENCHMARKS.md

Why I built this:
Most tutorials explain rate limiting with a simple in-memory counter or a basic redis.incr() call. In real systems, that breaks down:
1. In-memory counters multiply allowed quotas across worker instances behind a load balancer.
2. Naive Redis GET then SET commands leak under concurrency. In my 50-thread test, naive pipelines admitted 22 requests against a limit of 10.
3. Synchronous Redis calls in async frameworks block the event loop. Moving to redis.asyncio reduced median latency from 17 ms to 13 ms under 500 concurrent users.

What is included:
- Six algorithms: Fixed Window, Sliding Window Log, Sliding Window Counter, Token Bucket, Leaky Bucket, and GCRA.
- Atomic Lua scripts running inside Redis 7 to prevent race conditions.
- FastAPI middleware with tiered API key multipliers and endpoint trie routing.
- Circuit breaker to keep the gateway responsive if Redis drops out.
- Observability with Prometheus, Grafana, Loki JSON logging, and OpenTelemetry tracing.
- An interactive /compare endpoint to test algorithms against steady and bursty traffic patterns.

---

## 2. Reddit Post Outline

Title: I benchmarked 6 rate limiting algorithms in Python and Redis under load. Here are the tradeoffs.

Key discussion points:
- The window boundary leak problem and how to reproduce it.
- Why Token Bucket handles client bursts while Leaky Bucket forces smooth queues.
- Event loop stalls when mixing synchronous database drivers into async frameworks.
- Links to GitHub and the benchmark write-up.

---

## 3. Anticipated Questions & My Answers

### Why Python instead of Go or Rust for a rate limiter?
For an edge proxy handling millions of raw TCP connections, Go or Rust makes total sense. That is why Envoy and Cloudflare use them.

However, many backend services run on Python frameworks like FastAPI or Django. RateFortress shows that by pushing the rate calculation into Redis Lua scripts and keeping the Python layer asynchronous, an ASGI worker easily processes over 1,400 requests per second per core. It is also much easier to read and experiment with all six algorithms in Python.

### Why not just use Redis Cell?
Redis Cell is a solid Rust module for GCRA, but many managed cloud environments like AWS ElastiCache do not allow loading custom C or Rust modules. RateFortress uses vanilla Redis primitives and standard Lua scripts (EVALSHA), so it runs on any standard Redis provider without custom module installation.

### Isn't a fail-open circuit breaker dangerous during high traffic?
It is a choice between availability and strict limit enforcement. For standard customer-facing APIs, returning 500 errors to valid users during a brief Redis blip is usually worse than letting some extra traffic through.

For payment endpoints or SMS verification where excess requests cost real money, I recommend setting fail_open=False so the gateway fails closed. I documented this tradeoff in docs/tradeoffs.md.

### What happens when Redis runs low on memory?
First, every RateFortress key has an explicit TTL based on window length or refill time, verified in tests/test_redis_ttl_strategy.py.

Second, I recommend configuring Redis with maxmemory-policy volatile-lru so Redis evicts expiring rate limit keys under memory pressure without dropping persistent data.
