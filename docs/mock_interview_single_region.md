# Mock System Design Interview #1 — Single-Region Distributed Rate Limiter

This document captures a 45-minute senior system design interview walkthrough for designing a production-grade, distributed rate limiter protecting a high-throughput public API gateway.

---

## 1. Requirements Clarification (Minutes 0–5)

### Functional Requirements
1. **Accurate Throttling:** Throttle incoming HTTP/gRPC requests based on configurable rules:
   - Per client identity (authenticated API key / Tenant ID).
   - Per client IP address (unauthenticated public endpoints).
   - Per endpoint path with hierarchical rule inheritance (e.g. `/api/*` vs `/api/checkout`).
2. **Standardized Rejection:** When requests exceed quota, return HTTP `429 Too Many Requests` with RFC 6585 compliance:
   - `Retry-After: <seconds>` indicating when the client may retry.
   - `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` telemetry headers.
3. **Multi-Cost Consumption:** Support variable cost per request (e.g., standard ping = 1 token, batch inference or heavy export = 5 tokens).
4. **Dynamic Configuration:** Support tier overrides (free, paid, enterprise) without restarting gateway nodes.

### Non-Functional Requirements
1. **Ultra-Low Latency:** Adding rate limiting to the critical request path must not degrade user experience.
   - **Target:** $p95 < 1.0\text{ ms}$, $p99 < 2.0\text{ ms}$.
2. **High Availability:** Target 99.999% uptime. If rate limiter infrastructure fails, it must fail safely without taking down upstream business services.
3. **Strict Atomicity:** Distributed requests for the same client hitting different gateway workers concurrently must not suffer race conditions or over-admit traffic during bursts.
4. **Scalability:** Scale horizontally up to $1,000,000\text{ req/sec}$ across $10\text{M}$ daily active tenants.

---

## 2. Capacity & Back-of-the-Envelope Estimation (Minutes 5–8)

- **Traffic:** $1,000,000\text{ req/sec}$ peak.
- **Active Tenants:** $10,000,000$ daily keys, $\approx 1,500,000$ active concurrently in any 60-second window.
- **Algorithm Footprint:**
  - Token Bucket / GCRA: $\approx 124 - 144\text{ bytes per tenant}$.
  - Total RAM: $10\text{M} \times 144\text{ bytes} \approx 1.44\text{ GB}$ (with safety margin: $\approx 2.16\text{ GB}$).
- **Network Bandwidth:** $1\text{M req/s} \times 250\text{ B/check} \approx 250\text{ MB/s} = 2.0\text{ Gbps}$.
- **Storage Cluster:** Single Redis node handles $\approx 50,000\text{ Lua ops/sec}$.
  $$\text{Shards Needed} = \frac{1,000,000}{50,000} = 20\text{ Primary Shards} (+ 20\text{ Multi-AZ Replicas}) = 40\text{ Nodes}$$

---

## 3. High-Level Architecture (Minutes 8–18)

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

### Component Roles:
1. **Network Load Balancer (NLB):** Distributes incoming TCP connections evenly across gateway workers.
2. **Gateway Worker (RateFortress):** Lightweight ASGI proxy node executing the rate limit interceptor before forwarding traffic to upstream backend microservices.
3. **Endpoint Trie:** Prefix tree holding route rules, matching incoming paths in $O(k)$ time ($k = \text{path segments}$) without regular expressions.
4. **Redis Sharded Cluster:** Central state store holding atomic token bucket counters with automated TTL eviction.

---

## 4. Deep-Dive: Algorithm Choice & Race Condition Elimination (Minutes 18–28)

### Why Token Bucket / GCRA Over Sliding Window Log
- **Sliding Window Log Flaw:** Requires storing individual timestamps in a Redis `ZSET`. At $100\text{ req/min}$ per tenant, $10\text{M}$ active tenants demand **$>73\text{ GB}$ of RAM** and $O(\log N)$ insertions/deletions.
- **Token Bucket Advantage:** Constant $O(1)$ time, $O(1)$ space ($144\text{ bytes}$ per tenant). Permits bursts up to bucket capacity while enforcing smooth steady-state refill rate.
- **GCRA Advantage:** Even simpler; tracks a single Theoretical Arrival Time (TAT) scalar in a single Redis string key without requiring hash field parsing.

### Solving the Distributed Concurrency Race Condition
A naive implementation does:
```python
# BROKEN: Classic check-then-set race condition
current_tokens = redis.get(key)
if current_tokens >= 1:
    redis.set(key, current_tokens - 1)
    allow()
```
Under concurrent load with 10 workers, 10 requests can read `tokens = 1` simultaneously, admit 10 requests, and decrement to 0, resulting in **10x over-admission**.

**Solution — Redis Lua Scripting (`EVALSHA`):**
Redis executes Lua scripts single-threaded and atomically without yielding control mid-script:
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
    return {1, math.floor(tokens), 0} -- Allowed
else
    local needed = cost - tokens
    local retry_after = math.ceil(needed / refill_rate)
    return {0, math.floor(tokens), retry_after} -- Blocked
end
```

---

## 5. Fault Tolerance & Graceful Degradation (Minutes 28–35)

### Circuit Breaker Pattern
If Redis encounters network partition, latency spikes ($> 20\text{ ms}$), or crashes:
- The rate limiter must not block incoming user traffic.
- **Circuit Breaker States:**
  - **CLOSED:** Normal operation; all requests check Redis. If failure rate exceeds 50% over a 10s rolling window, trip to OPEN.
  - **OPEN:** Fast-fail circuit; bypass Redis entirely for 30s. Rate limiter immediately defaults to fallback policy without burning TCP timeouts.
  - **HALF-OPEN:** Probe with 10% canary traffic. If successful, reset to CLOSED; if failures persist, trip back to OPEN.

### Fail-Open vs Fail-Closed Policy
- **Standard Read / Content Endpoints (`GET /api/feed`):** **Fail-Open**. Serving user traffic takes priority over rate enforcement during an infrastructure incident.
- **Monetized / Critical Compute Endpoints (`POST /api/checkout`, `POST /api/generate`):** **Fail-Closed** with local fallback token bucket to prevent unbounded cloud spend or fraud.

---

## 6. Senior Interviewer Follow-Ups & Grilling (Minutes 35–45)

### Q1: "How do you handle Redis Cluster hash slot sharding when your Lua script accesses keys?"
> **Answer:** Redis Cluster partitions 16,384 hash slots across nodes using `CRC16(key) % 16384`. If a Lua script accesses multiple keys, Redis throws a `CROSSSLOT Keys in request don't hash to the same slot` error unless the keys share the same hash tag.
>
> In RateFortress, our core rate limiter design uses **single-key evaluation** per tenant (`{tenant_id}:tb`), ensuring 100% of data for a given tenant hashes to the exact same slot. Multi-key operations are strictly forbidden in our critical path Lua scripts.

### Q2: "What prevents Redis memory from exploding when millions of one-off bot IPs hit your gateway?"
> **Answer:** Two defense mechanisms:
> 1. **Automated Sliding TTL:** Every write in Lua attaches a strict TTL (`EXPIRE key window_seconds * 2`). Idle bot keys are passively evicted by Redis within 120 seconds of inactivity.
> 2. **Redis Eviction Policy:** Configure `maxmemory-policy volatile-lru` or `volatile-lfu`. If memory ever approaches instance limits, Redis drops keys with an expiring TTL that haven't been touched recently, prioritizing active valid subscribers.

### Q3: "What if client IPs are spoofed via `X-Forwarded-For`?"
> **Answer:** Blindly trusting `X-Forwarded-For` allows attackers to bypass IP rate limits by rotating arbitrary strings in headers.
>
> RateFortress implements **Trusted Proxy CIDR Verification**:
> We inspect the reverse-proxy chain right-to-left. If the immediate connection is from a known trusted proxy subnet (e.g. AWS ALB CIDR `10.0.0.0/16`), we traverse backward until we find the first non-trusted IP. If the peer is not in our trusted list, we discard the header completely and anchor limits to the raw TCP socket IP.
