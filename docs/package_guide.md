# RateFortress — Standalone Middleware Integration Guide

**Package Name:** `ratefortress`  
**License:** MIT  
**Compatibility:** FastAPI $\ge$ 0.100, Starlette $\ge$ 0.30, Python 3.11+  

---

## 1. Installation

Install via pip directly from the repository or your private index:

```bash
pip install ratefortress
# Or with optional gRPC microservice support:
pip install "ratefortress[grpc]"
```

---

## 2. Quickstart: 5-Line Integration

Drop RateFortress into any existing FastAPI application:

```python
from fastapi import FastAPI
import redis.asyncio as aioredis
from src.middleware.rate_limit_middleware import RateLimitMiddleware
from src.algorithms.async_redis_gcra import AsyncRedisGCRA

app = FastAPI(title="My High-Scale Service")

# 1. Connect to Redis
redis_client = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)

# 2. Instantiate your preferred algorithm (e.g. GCRA, TokenBucket, SlidingWindowCounter)
limiter = AsyncRedisGCRA(redis_client, limit=100, period=60.0)

# 3. Register the ASGI Middleware
app.add_middleware(RateLimitMiddleware, limiter=limiter)

@app.get("/items")
async def get_items():
    return [{"id": 1, "name": "Protected item"}]
```

Every response automatically receives standard RFC rate-limiting headers:
```http
HTTP/1.1 200 OK
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 99
X-RateLimit-Reset: 1730310000
```

When quota is exhausted:
```http
HTTP/1.1 429 Too Many Requests
Retry-After: 12
Content-Type: application/json

{"error": "rate limit exceeded"}
```

---

## 3. Tiered Limits & Route-Specific Quotas

RateFortress supports hierarchical route prefix matching via an internal `EndpointTrie`:

```python
from src.middleware.config import EndpointRule
from src.middleware.endpoint_trie import EndpointTrie

trie = EndpointTrie()

# Global default: 60 req/min
trie.insert("/", EndpointRule(limit=60, window_seconds=60))

# Strict quota on sensitive or expensive operations
trie.insert("/api/ai-generation", EndpointRule(limit=5, window_seconds=60))

# Relaxed quota for administrative users
trie.insert("/api/admin/*", EndpointRule(limit=500, window_seconds=60))
```

---

## 4. Resilience & Fail-Open Behavior

In cloud environments where Redis might experience momentary failover or network partitioning, RateFortress ensures your API remains available:

```python
from src.middleware.circuit_breaker import CircuitBreaker

# Automatically fails open on storage downtime
breaker = CircuitBreaker(failure_threshold=5, recovery_timeout_sec=15.0, fail_open=True)
```
