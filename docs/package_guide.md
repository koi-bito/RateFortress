# RateFortress — Standalone Middleware Integration Guide

- Package Name: ratefortress
- License: MIT
- Compatibility: FastAPI >= 0.100, Starlette >= 0.30, Python 3.11+

---

## 1. Installation

Install via pip from the local repository or a wheel build:
```bash
pip install ratefortress
# Or with optional gRPC support:
pip install "ratefortress[grpc]"
```

---

## 2. Quickstart: 5-Line Integration

Here is how I plug RateFortress into an existing FastAPI application:

```python
from fastapi import FastAPI
import redis.asyncio as aioredis
from src.middleware.rate_limit_middleware import RateLimitMiddleware
from src.algorithms.async_redis_gcra import AsyncRedisGCRA

app = FastAPI(title="My Service")

# 1. Connect to Redis
redis_client = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)

# 2. Instantiate algorithm
limiter = AsyncRedisGCRA(redis_client, limit=100, period=60.0)

# 3. Register the ASGI Middleware
app.add_middleware(RateLimitMiddleware, limiter=limiter)

@app.get("/items")
async def get_items():
    return [{"id": 1, "name": "Protected item"}]
```

Every response receives standard rate limit headers:
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

RateFortress supports hierarchical route prefix matching using an internal EndpointTrie:

```python
from src.middleware.config import EndpointRule
from src.middleware.endpoint_trie import EndpointTrie

trie = EndpointTrie()

# Global default: 60 req/min
trie.insert("/", EndpointRule(limit=60, window_seconds=60))

# Tighter limit on expensive operations
trie.insert("/api/ai-generation", EndpointRule(limit=5, window_seconds=60))

# Relaxed limit for admin routes
trie.insert("/api/admin/*", EndpointRule(limit=500, window_seconds=60))
```

---

## 4. Resilience & Fail-Open Behavior

If Redis experiences a failover or brief network issue, the circuit breaker keeps the API responsive by failing open:

```python
from src.middleware.circuit_breaker import CircuitBreaker

# Fails open on storage downtime
breaker = CircuitBreaker(failure_threshold=5, recovery_timeout_sec=15.0, fail_open=True)
```
