# Mock System Design Interview: Single-Region Distributed Rate Limiter

These are my walkthrough notes for a 45-minute system design interview on building a distributed rate limiter for a public API gateway.

---

## 1. Requirements Clarification

### Functional Requirements
1. Throttling rules: Throttle incoming HTTP and gRPC requests by client identity (API key or tenant ID), client IP for unauthenticated routes, and route path with prefix matching.
2. Standard rejection: When quota is exceeded, return HTTP 429 Too Many Requests with Retry-After and X-RateLimit headers.
3. Variable cost: Support different costs per request (such as 1 token for a GET and 5 tokens for a heavy batch export).
4. Dynamic tiers: Support tier overrides (free, paid, enterprise) without restarting gateway workers.

### Non-Functional Requirements
1. Low latency: Adding rate limiting to the critical request path must stay under 2.0 ms at p99.
2. High availability: If the rate limiter backend fails, it must fail safely without bringing down the core application.
3. Strict atomicity: Requests for the same user hitting different gateway workers concurrently must not cause race conditions.
4. Scale: Handle up to 1,000,000 requests per second across 10 million daily active keys.

---

## 2. Capacity & Estimation

- Peak traffic: 1,000,000 req/sec peak, 400,000 req/sec average.
- Active keys: 10,000,000 daily keys, with roughly 1,500,000 active in any 60-second window.
- Memory: Token Bucket and GCRA take about 124 to 144 bytes per key in Redis. 10 million keys take around 1.44 GB, or roughly 2.16 GB with jemalloc memory safety buffer.
- Network bandwidth: 1,000,000 req/sec * 250 bytes per check = 250 MB/s = 2.0 Gbps.
- Storage cluster: A single Redis primary handles roughly 50,000 Lua operations per second before queueing delays set in. Sizing for peak requires 1,000,000 / 50,000 = 20 primary shards, plus 20 replicas for multi-AZ availability (40 nodes total).

---

## 3. High-Level Architecture

```
[Clients: Mobile / Web / 3rd-Party API]
                   │
                   ▼ (HTTPS / TLS Termination)
       [Layer 4 Network Load Balancer]
                   │
          ┌─────────┴─────────┐
          ▼                   ▼
   [Gateway Worker 1]   [Gateway Worker N] (FastAPI / Envoy)
    ├── Endpoint Trie Matcher (O(k) path lookup)
    ├── Identity Resolver (API Key / Trusted Proxy CIDR IP)
    ├── Circuit Breaker (Fail-open guardian)
    └── RateLimiter Middleware
          │                   │
          └─────────┬─────────┘
                    ▼ (Redis Binary Protocol / Connection Pool)
        [Redis Cluster — 20 Shards]
        ├── Shard 1 ({tenant_A})
        ├── Shard 2 ({tenant_B})
        └── ...
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
 [Allowed: Forward to App]  [Blocked: Return 429 + Retry-After]
```

Component responsibilities:
1. Network Load Balancer: Distributes TCP connections across gateway workers.
2. Gateway Workers: Lightweight proxy processes running middleware to check rate limits before forwarding traffic to downstream services.
3. Endpoint Trie: Matches paths in O(k) time where k is segment count, avoiding regular expression bottlenecks.
4. Redis Cluster: Stores centralized token bucket counters with automatic TTL expiration.

---

## 4. Algorithm Choice & Concurrency

### Why Token Bucket or GCRA over Sliding Window Log
Sliding Window Log requires storing individual timestamps in a Redis sorted set (ZSET). At 100 requests per minute per user, 10 million active users require over 73 GB of RAM and O(log N) operations.

Token Bucket operates in constant O(1) time and space (roughly 144 bytes per key). It allows brief bursts while capping sustained throughput. GCRA operates similarly by tracking a single Theoretical Arrival Time timestamp in a Redis string key (around 124 bytes).

### Eliminating Distributed Concurrency Race Conditions
A naive implementation reads the counter and then writes the incremented value in separate steps:
```python
# Broken check-then-set race condition
current_tokens = redis.get(key)
if current_tokens >= 1:
    redis.set(key, current_tokens - 1)
    allow()
```

Under concurrent load across multiple workers, multiple requests read the same initial value and pass before any write commits, causing over-admission.

I solved this by moving the entire check and decrement logic into atomic Redis Lua scripts executed with EVALSHA. Because Redis runs Lua scripts on its single execution thread without interleaving other commands, reads and updates happen in a single atomic step.

```lua
-- Atomic Token Bucket Lua Script
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local data = redis.call('HMGET', key, 'tokens', 'last_refilled')
local tokens = tonumber(data[1])
local last_refilled = tonumber(data[2])

if not tokens then
    tokens = capacity
    last_refilled = now
else
    local delta = math.max(0, now - last_refilled)
    tokens = math.min(capacity, tokens + delta * refill_rate)
    last_refilled = now
end

if tokens >= cost then
    tokens = tokens - cost
    redis.call('HMSET', key, 'tokens', tokens, 'last_refilled', last_refilled)
    redis.call('EXPIRE', key, ttl)
    return {1, math.floor(tokens), 0}
else
    local needed = cost - tokens
    local retry_after = math.ceil(needed / refill_rate)
    return {0, math.floor(tokens), retry_after}
end
```

---

## 5. Fault Tolerance & Graceful Degradation

### Circuit Breaker Pattern
If Redis encounters network timeouts or crashes, the rate limiter must not block customer traffic:
- Closed state: Normal operation where requests check Redis. If failure rate exceeds 50% over a 10s window, the circuit trips open.
- Open state: Fast-fail circuit that bypasses Redis entirely for 30s, allowing requests through immediately without burning socket timeouts.
- Half-open state: Probes with canary traffic. If successful, resets to closed; if failures persist, trips back open.

### Fail-Open vs Fail-Closed Policy
For standard read endpoints, fail-open is the right default: serving traffic during an infrastructure incident is better than returning 500 errors to valid users.

For expensive operations like checkout or AI model generation, setting fail_open=False to fail closed protects downstream infrastructure from unlimited runaway calls.

---

## 6. Follow-Up Questions

### How do you handle Redis Cluster sharding with Lua scripts?
Redis Cluster maps keys across 16,384 hash slots. If a Lua script accesses multiple keys that hash to different slots, Redis returns a CROSSSLOT error.

In RateFortress, I designed every rate limiter script to operate strictly on a single key (`KEYS[1]`). All data for a tenant hashes to the exact same slot, eliminating cross-slot errors.

### What prevents Redis from running out of memory from bot IPs?
First, every Lua update sets a strict TTL (such as double the window length). Idle bot keys expire automatically after a couple of minutes of inactivity.

Second, configuring Redis with `maxmemory-policy volatile-lru` ensures that under memory pressure, Redis evicts keys with an active TTL that have not been touched recently.

### What if client IPs are spoofed in X-Forwarded-For?
Blindly trusting X-Forwarded-For lets attackers rotate random IP strings in headers to bypass limits.

RateFortress checks trusted proxy CIDRs from right to left. If the incoming socket IP is in a trusted proxy range, it traverses backwards to find the first untrusted client IP. If the socket connects directly from an untrusted IP, the header is discarded and the limit binds to the socket IP.
