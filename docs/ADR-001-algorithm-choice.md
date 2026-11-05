# ADR-001: Choosing Token Bucket and GCRA as Default Algorithms

- **Status:** Accepted
- Date: 2026-10-30
- Author: Solo Developer

---

## 1. Context and Problem Statement

An API gateway needs to protect downstream services from spikes and abusive scrapers without punishing legitimate users who load a page and trigger several requests at once.

I evaluated the algorithms against four requirements:
1. Low evaluation latency: under 1.5 ms on Redis and under 1 microsecond in local memory.
2. Low memory usage: O(1) space per client, keeping key sizes around 150 bytes so Redis memory does not explode under millions of active keys.
3. Burst tolerance: allowing brief bursts for page loads while holding the long-term consumption to a steady rate.
4. Variable request costs: supporting heavier endpoints that consume multiple units of quota in one call.

---

## 2. Decision

I chose Token Bucket as the default rate limiting algorithm for RateFortress routes, with GCRA (Generic Cell Rate Algorithm) as the alternative when Redis memory is at a premium.

All routes use Token Bucket unless specifically configured otherwise in the endpoint trie.

---

## 3. Alternatives Considered

### Alternative 1: Fixed Window Counter
Fixed Window divides time into fixed blocks (such as 00:00 to 00:59) and increments a counter. I rejected it because of the 2x boundary spike problem: a user can send their full limit right at 00:59 and another full limit at 01:00, allowing double the allowed quota in two seconds.

### Alternative 2: Sliding Window Log
Sliding Window Log stores every request timestamp in a Redis sorted set (ZSET) and trims old timestamps. I rejected it as a default because of high memory usage. At 100 requests per minute per user, each user takes over 7 KB of RAM. Across millions of keys, that turns into tens of gigabytes of Redis memory, and sorting operations scale with window size rather than running in constant time.

### Alternative 3: Sliding Window Counter
Sliding Window Counter estimates current volume by blending the current window count with a weighted slice of the previous window. It only takes around 150 bytes per user, but it is an approximation that assumes requests in the previous window were evenly spread.

### Alternative 4: Leaky Bucket
Leaky Bucket processes requests at a constant leak rate. I decided against it as the default because it allows zero bursts. If an idle client opens several parallel connections to fetch page assets, Leaky Bucket throttles them immediately even though they used no prior bandwidth.

---

## 4. Benchmark Results

I tested each implementation in local Python and in Redis with Lua scripts:

| Algorithm | Local Python Throughput | Redis Lua Throughput | Memory / Key | Exactness | Bursts Allowed? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GCRA** | **$3,303,492\text{ req/s}$** | **$6,695\text{ req/s}$** | **$124\text{ B}$** | Exact | Yes (Bounded) |
| **Token Bucket** | **$2,169,380\text{ req/s}$** | **$6,540\text{ req/s}$** | **$144\text{ B}$** | Exact | Yes (Bounded) |
| **Sliding Window Counter** | $1,784,210\text{ req/s}$ | $6,310\text{ req/s}$ | $150\text{ B}$ | Approx (±5%) | Yes (Smoothed) |
| **Fixed Window** | $2,450,110\text{ req/s}$ | $6,720\text{ req/s}$ | $112\text{ B}$ | Exact | Flawed ($2\times$) |
| **Sliding Window Log** | $1,120,450\text{ req/s}$ | $4,890\text{ req/s}$ | $7,300\text{ B}$ | Exact | Strict |

GCRA achieved slightly higher throughput because it updates only a single timestamp (the theoretical arrival time) instead of refilling and decrementing token counts. Token Bucket offers better developer usability, since remaining tokens directly map to the X-RateLimit-Remaining header.

---

## 5. Consequences & Operational Notes

- Predictable memory: Memory usage scales linearly at roughly 144 bytes per key in Redis, so 10 million keys take around 2.2 GB.
- Constant time evaluation: Both Token Bucket and GCRA run in O(1) arithmetic operations inside single Redis Lua executions.
- Variable costs: Deducting multiple tokens for an expensive route requires only a single decrement parameter.
- Downstream protection: If a bucket has a capacity of 100, a client can dump 100 calls in milliseconds. To protect fragile downstream services, I recommend using shorter refill intervals (such as 10 tokens per second with a burst of 15) rather than large minute-long windows.
- Clock synchronization: Both algorithms depend on accurate time, so all Redis evaluations use redis.call('TIME') to avoid client clock drift.
