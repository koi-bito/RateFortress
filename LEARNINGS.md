# RateFortress : Daily Engineering Log & Learnings

A personal log tracking architectural decisions, bugs, and lessons learned while building RateFortress.

---

## Week 0 : Foundations (Days 1-5)

### Day 1 : Why Rate Limiting Exists
I spent way too long reading about API outages before writing anything. If you do not rate limit, an unindexed database query hit 10,000 times a second just brings down the whole stack. Or someone scripts your free trial and runs up a huge bill before morning.

### Day 2 : The Five Core Algorithms
Looked at the five classic algorithms. Payments need something like Token Bucket or Sliding Window Log because money transactions cannot have surprise spikes. For search autocomplete, Sliding Window Counter makes way more sense because dropping a keystroke is fine, but adding latency is not.

### Day 3 : DSA: Hashmaps, Deques & Circular Buffers
Took me a while to realize why a Python list pop(0) is so bad here. Shifting all elements in memory every single time you evict an old timestamp kills performance. Switched my thinking to collections.deque, which gives O(1) pops from the left.

### Day 4 : DSA: Heaps & Consistent Hashing
Min-heaps give O(log n) inserts and O(1) peek, which I used for prioritizing requests under heavy load. Consistent hashing is how keys get spread across multiple storage nodes without reshuffling everything.

### Day 5 : Project Scoping & Manual Simulation
Drew out the boundary problem on paper. If a user sends five requests at second 9 and five requests at second 10 on a 10-second window, Fixed Window lets all 10 through. That is double the limit. Seeing it visually made the problem obvious.

---

## Week 1 : Environment Setup & Project Scaffold (Days 6-10)

### Day 6 : Modular Architecture Separation
Split the repo into algorithms, middleware, storage, and api. It felt like too much boilerplate at first, but keeping pure algorithm logic away from FastAPI will save me headaches in tests.

### Day 7 : Commit Message Conventions
Decided to stick to simple git commit prefixes like feat, test, and fix. Keeps the log clean.

### Day 8 : Test-Driven Development (TDD)
Wrote unit tests before writing the actual rate limit code. Testing boundary conditions first caught several off-by-one errors I definitely would have introduced.

### Day 9 : Unified Benchmark Harness
Built a basic runner script so I can benchmark all algorithms with the same synthetic traffic. If the harness is not identical, the numbers mean nothing.

### Day 10 : Week 1 Review
Reviewed the scaffolding and got all initial tests green. Ready to actually build Fixed Window.

---

## Week 2 : Fixed Window & Sliding Window Log (Days 11-15)

### Day 11 : Fixed Window Counter Mechanics
Implemented Fixed Window with a basic dictionary. It is fast and simple, but the boundary doubling problem is very real.

### Day 12 : Testing & Benchmarking Fixed Window
Ran benchmarks on Fixed Window. Got around 2.8 million requests per second in pure Python memory. It is fast because it is literally just integer additions.

### Day 13 : Sliding Window Log Mechanics
Built Sliding Window Log using collections.deque. It completely fixes the boundary problem because it checks a rolling window, but storing every single timestamp in memory will get expensive fast.

### Day 14 : Testing & Benchmarking Sliding Window Log
Clocked Sliding Window Log at roughly 3.4 million requests per second in memory. The speed is great, but the memory footprint scales directly with request volume.

### Day 15 : Empirical Comparison (Fixed Window vs. Sliding Window Log)
Wrote a test script to slam the window boundary. Fixed Window leaked 10 out of 10 requests, while Sliding Window Log cut off at exactly 5. Nice to see the math hold up in code.

---

## Week 3 : Sliding Window Counter, Token Bucket & Leaky Bucket (Days 16-21)

### Day 16 : Sliding Window Counter Mechanics
Built Sliding Window Counter using a weighted sum of the previous and current window counts. It only stores two numbers per client, giving constant space while smoothing out the boundary spike. Not exact, but easily close enough.

### Day 17 : Token Bucket Mechanics
Implemented Token Bucket. I refilled tokens lazily on each request based on elapsed time rather than using a background thread. Simple, zero thread overhead, and supports bursts up to capacity.

### Day 18 : Leaky Bucket Mechanics
Built Leaky Bucket with a constant leak rate. Unlike Token Bucket, it smooths out traffic completely and never allows bursts, which is great for protecting fragile backends.

### Day 19 : Full 5-Algorithm Benchmark Suite
Benchmarked all five in-memory limiters side by side. Sliding Window Log and Fixed Window were fastest, but Sliding Window Counter feels like the right default for real services.

### Day 20 : DSA Practice Day: Core Patterns
Spent time doing sliding window and heap problems on LeetCode. Re-implemented monotonic deques from scratch to stay sharp on the pointers.

### Day 21 : Week 3 Review & Milestone Complete
First big milestone done. All five core algorithms working in-memory with tests passing.

---

## Week 4 : FastAPI Middleware Layer I (Days 22-27)

### Day 22 : ASGI Architecture & Uvicorn
Set up FastAPI and Uvicorn. Spent some time understanding ASGI scopes and how requests flow through middleware layers before hitting route handlers.

### Day 23 : Middleware Dispatch Pipeline
Wrote custom BaseHTTPMiddleware to intercept requests. It extracts client identity, checks the limiter, and either lets the call through or returns a 429.

### Day 24 : Rate Limit Headers on Every Response
Added standard headers: X-RateLimit-Limit, Remaining, Reset, and Retry-After. Figuring out how to compute Retry-After accurately across different algorithms took longer than expected.

### Day 25 : Per-Endpoint Quota Isolation
Added route-specific overrides. I wanted expensive endpoints like /search to have tight limits while health checks stay open.

### Day 26 : API Key Security & Tier Multipliers
Added API key handling with tier multipliers. Free tier gets 1x quota, paid gets 10x, and enterprise gets 50x. Falls back to client IP for anonymous requests.

### Day 27 : DSA Practice: Hashing & Design Patterns
Practiced hashmap caching problems. Made sure key lookups in middleware remain constant time so they do not add latency to requests.

---

## Week 5 : FastAPI Middleware Layer II, Tiering, Resilience & Load Prep (Days 28-33)

### Day 28 : Tiered Rate Limits with Priority Queues
Built an in-memory priority queue using heapq. When active requests get close to saturation, free tier calls get dropped immediately with 503 so paid users still get through.

### Day 29 : Endpoint Trie for Prefix Matching
Wrote an EndpointTrie so I do not have to do linear regex matching across routes. Route lookups now take time proportional to path length, which is much faster.

### Day 30 : Full Middleware Integration Testing
Wrote integration tests covering key tiers, route overrides, and header values. Hit a silly bug where missing headers caused a KeyError, but fixed it with proper defaults.

### Day 31 : Live Request Burst Throttling
Fired 30 rapid curl requests at an endpoint limited to 10. The first 10 succeeded, and request 11 immediately returned 429 with Retry-After. Good to see it work against a real server.

### Day 32 : Circuit Breaker & Resilience Policies
Added a circuit breaker pattern around storage calls. If Redis fails consecutively, the breaker trips open and lets traffic through instead of hanging the entire API gateway.

### Day 33 : Week 5 Review & Completion
Cleaned up middleware code and verified all integration tests pass before starting the Redis backend.

---

## Week 6 : Redis Backend I (Days 34-39)

### Day 34 : Why In-Memory Breaks in Production & Redis Setup
Ran two Uvicorn workers and realized in-memory counters do not share state. A user could double their limit just by hitting alternating workers. Spun up Redis in Docker to centralize state.

### Day 35 : Redis Fixed Window & The Danger of GET-then-SET
Implemented Fixed Window in Redis using INCR and EXPIRE. I noticed early on that doing GET then SET in separate commands causes bad race conditions under concurrency.

### Day 36 : Redis Sliding Window Counter & Distributed Tradeoffs
Ported Sliding Window Counter to Redis using two keys for current and previous windows. It works, but making multiple network round-trips per request adds unnecessary latency.

### Day 37 : Sliding Window Log via Redis Sorted Sets (ZSET)
Implemented Sliding Window Log in Redis with sorted sets. Used timestamps for both score and value, trimming old entries with ZREMRANGEBYSCORE. Works nicely, but Redis memory usage climbs fast.

### Day 38 : Test Isolation & Redis Database Indexing
Added fakeredis for running unit tests without needing an external Redis container running. Saved me from having tests fail in environments without network access.

### Day 39 : DSA Practice: Tries vs. Hashmaps for Routing
Compared trie lookup speeds against flat dictionary lookups. For exact matches, hashmaps win, but tries are much better when dealing with path prefixes and wildcards.

---

## Week 7 : Redis Backend II, Lua Scripts, Atomicity & Eviction (Days 40-45)

### Day 40 : Token Bucket via Redis + Lua Scripts
Wrote a Lua script for Token Bucket and loaded it with EVALSHA. Running the token calculation directly inside Redis stopped the race conditions completely.

### Day 41 : Leaky Bucket via Redis + Lua Scripts
Wrote a Lua script for Leaky Bucket. It updates water levels and timestamps in a single atomic pass, making sure requests leak at the exact right rate across workers.

### Day 42 : Atomicity Deep Dive & Race Condition Elimination
Ran a 50-thread concurrent stress test against non-atomic Redis pipelines versus Lua scripts. The non-atomic code allowed 22 requests through a limit of 10. The Lua script allowed exactly 10. That was satisfying to prove.

### Day 43 : Distributed Multi-Instance Validation
Spun up two gateway instances pointing at the same Redis container. Fired requests at both and confirmed the shared quota was respected across instances.

### Day 44 : Key Eviction & TTL Strategy
Audited Redis TTL settings across all keys. Added dynamic TTLs so inactive client keys expire automatically instead of bloating Redis memory forever.

### Day 45 : Week 6-7 Review & Milestone Complete
All six algorithms now have distributed Redis implementations with atomic Lua scripts. Concurrency tests are passing.

---

## Week 8 : Load Testing with Locust (Days 46-51)

### Day 46 : Locust Setup & First Load Test
Configured Locust to simulate multi-tenant user traffic. Ran an initial baseline test to make sure the load generator machine was not bottlenecked.

### Day 47 : Simulate 100 Concurrent Users
Ramped to 100 concurrent users. Median latency stayed around 2 ms, and everything looked rock solid.

### Day 48 : Simulate 500 Concurrent Users & Async Redis Migration
At 500 users, the synchronous redis client started blocking the FastAPI event loop. Switched to redis.asyncio and median latency dropped from 17 ms to 13 ms. Should have used async Redis from day one.

### Day 49 : Simulate 1000 Concurrent Users & Stress Breaking Point
Pushed up to 1,500 users to see where things break. Throughput capped around 1,420 req/s as the single Python worker maxed out one CPU core.

### Day 50 : Document Latency & Benchmarking Matrix
Collected all latency percentiles across the Locust runs. Wrote down p50, p95, and p99 numbers to keep track of queueing behavior under saturation.

### Day 51 : DSA Practice Day: Queues & Concurrency
Spent time studying event loop scheduling and asynchronous queues. Made it much clearer why synchronous socket calls stall async Python applications.

---

## Week 9 : Load Testing II (k6), Spike & Soak Testing (Days 52-56)

### Day 52 : k6 Setup & Comparison Test
Installed k6 and ported the load tests to JavaScript. Noticeably lower CPU usage on my machine compared to Locust.

### Day 53 : Locust vs. k6, Empirical Comparison
Ran 500 users on both tools. Both showed around 19 ms median latency, but k6 caught higher tail spikes because its Go runtime does not suffer from Python GIL pauses.

### Day 54 : Spike Testing & Failure Mode Analysis
Shock-tested the service by jumping from 10 to 1,500 users in 3 seconds. The OS TCP listen backlog filled up and dropped connections with resets. Once the spike cleared, latencies recovered immediately.

### Day 55 : Soak Testing & Memory Leak Verification
Ran 120 users continuously while logging memory with psutil. Memory stayed completely flat at 4.5 MB, proving there are no connection leaks or runaway key sets.

### Day 56 : Finalize Benchmark Report & Milestone Review
Consolidated all numbers into BENCHMARKS.md. It feels good having real data backing every design decision instead of theoretical guesses.

---

## Week 10 : Observability: Prometheus (Days 57-61)

### Day 57 : Prometheus Fundamentals
Read through Prometheus metric conventions. Decided on counters for requests and throttled responses, plus a histogram for latency tracking.

### Day 58 : Instrument FastAPI with prometheus-client
Added prometheus-client and created a /metrics endpoint. Wrapped middleware logic to record request counts and execution times.

### Day 59 : Track Request/Block Counters Per User/Algorithm & Latency Histograms
Added labels for route, algorithm, tier, and outcome. Had to be careful not to include unique client IDs as labels to avoid high-cardinality memory issues in Prometheus.

### Day 60 : Prometheus Local Setup via Docker
Added a Prometheus container in docker-compose.yml to scrape the gateway every few seconds. Verified that metrics were arriving properly in the Prometheus expression browser.

### Day 61 : Query Metrics with PromQL
Practiced writing PromQL queries for 95th percentile latency and per-second block rates. Took me a bit to get histogram_quantile syntax right.

---

## Week 11 : Observability: Grafana, Logs & Tracing (Days 62-66)

### Day 62 : Grafana Setup & Docker Compose Orchestration
Provisioned Grafana with automatic Prometheus datasource mounting. No manual clicking required after docker compose up.

### Day 63 : Live Observability Dashboard Panels
Built dashboard panels for throughput, 429 percentages, and latency percentiles. Watching real-time graphs respond to load tests made debugging much easier.

### Day 64 : Structured JSON Logging & Loki Aggregation
Switched logs to structured JSON and piped them into Loki with Promtail. Now I can query logs by request ID and client tier in Grafana.

### Day 65 : Distributed Tracing with OpenTelemetry
Added OpenTelemetry spans around rate limit evaluations and Redis calls. It shows exactly how many microseconds were spent waiting on Redis versus running Python code.

### Day 66 : SLA Alerting Rules & Stack Review
Configured alert rules for sustained 429 spikes and high error rates. Full observability stack is working together smoothly.

---

## Week 12 : Algorithm Comparison Engine (Days 67-71)

### Day 67 : Designing the `/compare` Response Contract First
Designed the JSON response structure for /compare before writing any logic. Having a clear schema first kept the implementation focused.

### Day 68 : Multi-Algorithm Simulation Engine (`src/api/compare.py`)
Built the comparison engine to run synthetic traffic through all six algorithms simultaneously. It tracks allowed counts, blocked counts, and timings across identical request sequences.

### Day 69 : Qualitative Tradeoff Matrix & Single-Scenario Best Choices
Wrote docs/tradeoffs.md summarizing when to pick each algorithm. Token Bucket for APIs that allow bursts, Leaky Bucket for smooth queues, and GCRA when memory is tight.

### Day 70 : Fairness Simulation: Bursty vs. Steady Clients
Added a simulation testing uniform versus skewed client traffic. Highlighted how aggressive clients can starve steady users if quotas are not partitioned properly.

### Day 71 : Content Negotiation & Jinja2 HTML Presentation
Built a browser-accessible HTML view for /compare using Jinja2 templates. Now anyone can test algorithms and view comparative tables directly in a web browser.

---

## Week 13 : Dockerization & Cloud Deployment (Days 72-76)

### Day 72 : Hardened Dockerization & Container Architecture
Wrote a Dockerfile using python:3.13-slim. Configured a non-root user and health checks to keep the container safe and clean.

### Day 73 : Full-Stack Docker Compose Orchestration
Combined the gateway, Redis, Prometheus, Grafana, Loki, and Promtail into one docker-compose.yml. The whole stack spins up cleanly with a single command.

### Day 74 : Cloud Hosting Selection & Architecture Tradeoffs
Wrote deployment blueprints for Render and Railway. Evaluated tradeoffs between PaaS platforms and raw EC2 instances for running the stack.

### Day 75 : Secrets Management & Environment Configuration
Configured environment variables for Redis connections and admin keys. Verified that the app falls back safely if secret keys are missing.

### Day 76 : Automated Deployment Smoke Testing
Wrote scripts/smoke_test_deployment.py to test health endpoints and rate limit headers against the live deployment. All checks passed with low latency.

---

## Week 14 : CI/CD, Blue-Green Deploys & Rollback (Days 77-81)

### Day 77 : Continuous Integration with Real Redis Services
Set up GitHub Actions to run pytest across Python 3.11, 3.12, and 3.13 with a live Redis service container. Tests run on every push.

### Day 78 : Automated Continuous Deployment on Push
Added auto-deployment on main branch merges once tests pass.

### Day 79 : Blue-Green Zero-Downtime Deployment
Documented blue-green cutover steps to switch traffic between instances without dropping in-flight requests.

### Day 80 : Incident Drill & Production Rollback Runbook
Wrote an incident response runbook in docs/runbook.md and practiced rolling back a simulated failure. Good to have the exact rollback commands written down before something goes wrong.

### Day 81 : Pipeline Review & Production Badges
Added status badges to the README and verified the entire CI/CD pipeline runs without flake.

---

## Week 15 : Documentation, Demo, Interview Prep & Resume Bullet (Days 82-86)

### Day 82 : End-to-End System Architecture Diagram
Drew the full system architecture diagram in docs/architecture.svg, illustrating request flow from client to Redis Lua scripts.

### Day 83 : Recruiter-Ready README & 60-Second Comprehension
Rewrote the README to be straightforward and clear about what RateFortress actually does, cutting out buzzwords.

### Day 84 : Video Demo Walkthrough & Public Launch
Wrote a video demo walkthrough script covering live throttling, the compare engine, and Grafana dashboards.

### Day 85 : System Design Mock Interview Prep & Technical Defense
Wrote out answers to common rate limiter interview questions in docs/interview_prep_and_defense.md, covering race conditions, storage sizing, and fail-open policies.

### Day 86 : Code Quality Audit & High-Impact Resume Bullets
Cleaned up comments, ran the full test suite, and summarized what the project demonstrates without corporate filler.

---

## Weeks 16-20 : Research Layer & Optional Extensions (Days 87-100)

### Day 89 : Developer Publication Syndication (`docs/devto_article.md`)
Drafted an article explaining the window boundary leak and why Redis Lua scripts are necessary to prevent race conditions.

### Day 90 : Community Showcase & Technical Defense (`docs/community_showcase_and_defense.md`)
Compiled technical defense talking points addressing common questions about Redis persistence and distributed consensus.

### Day 91 : Post-Launch Lessons Learned (`docs/lessons_learned_followup.md`)
Wrote down mistakes I made during development, including using sync Redis inside async FastAPI routes and underestimating connection pool tuning.

### Day 92 : 6th Algorithm: GCRA (Generic Cell Rate Algorithm)
Implemented GCRA in Python and Redis Lua. It tracks a single theoretical arrival time per user, providing accurate rate limiting with minimal memory.

### Day 93 : Redis Cluster & Sharding Architecture (`docs/scaling.md`)
Documented how to shard keys across Redis Cluster nodes using hash tags so multi-key Lua operations stay on the same slot.

### Day 94 : High-Throughput gRPC Alternative Interface
Added a gRPC service using Protocol Buffers in src/grpc_service/, providing a fast binary transport option alongside REST.

### Day 95 : Reusable Middleware Package (`pyproject.toml`)
Packaged the middleware into a clean Python library with pyproject.toml so it can be installed independently.

### Day 96 : Security Hardening & Zero-Downtime Key Rotation
Audited header parsing and added key rotation logic so old keys remain valid during a migration grace period.

### Day 100 : Capstone Milestone Reached & Retrospective
Reviewed the core project. Having 165 automated tests passing made refactoring safe throughout.

---

## Week 21 : Adversarial Testing & Abuse Simulation (Days 101-105)

### Day 101 : Real-World Rate Limit Bypass Techniques
Researched how attackers get around rate limiters using IP spoofing headers, rotated credentials, and distributed client networks.

### Day 102 : Attacker Simulation Script (`loadtests/adversary_simulation.py`)
Wrote a test script that attempts to spoof X-Forwarded-For headers and rotate client IPs rapidly to bypass limits.

### Day 103 : Hardening Defenses: Trusted Proxy Validation (`src/middleware/trusted_proxy.py`)
Built CIDR-based proxy validation so X-Forwarded-For headers are only trusted if the immediate upstream client IP is in a configured proxy list.

### Day 104 : Defense in Depth: Behavioral Anomaly Detection (`src/middleware/behavioral_shield.py`)
Added a simple behavioral shield that tracks 429 frequency per IP and temporarily clamps down on suspicious traffic patterns.

### Day 105 : Red Team Report & Evolution of Understanding
Documented the adversary test findings in docs/redteam_report.md, showing that trusting arbitrary headers makes IP-based rate limiting useless.

---

## Week 22 : System Design Interview Mastery (Days 106-110)

### Day 106 : Capacity Planning & Back-of-the-Envelope Math (`docs/capacity_planning.md`)
Calculated Redis memory and bandwidth requirements for 1 million requests per second. Made sure to account for Redis hash overhead in addition to raw values.

### Day 107 : Mock Interview #1: Single-Region Gateway (`docs/mock_interview_single_region.md`)
Wrote out a full transcript for a single-region rate limiter interview, focusing on SLA requirements, storage trade-offs, and fail-open defaults.

### Day 108 : Mock Interview #2: Multi-Region Global Topology (`docs/mock_interview_multi_region.md`)
Documented a multi-region design where local clusters lease quota batches from a central store to avoid cross-region network latency on every request.

### Day 109 : Architecture Decision Record (`docs/ADR-001-algorithm-choice.md`)
Wrote ADR-001 documenting why Token Bucket and GCRA were chosen as default algorithms over Sliding Window Log.

### Day 110 : Review, Interview Prep & Automated Math Validation
Wrote tests in tests/test_system_design_calculations.py to verify that capacity sizing formulas stay consistent and pass automated assertions.

---

## Week 23 : Multi-Tenant Admin Dashboard (Days 111-115)

### Day 111 : Designing the Multi-Tenant Admin API (`src/api/admin.py`)
Built REST endpoints to issue, view, update, rotate, and revoke API keys, secured by an admin secret header.

### Day 112 : Persistent Key Store (`src/storage/key_store.py` & `scripts/seed_admin_keys.py`)
Built RedisKeyStore to persist key metadata in Redis hashes and index active keys, with an in-memory fallback for local testing.

### Day 115 : Integration Testing & Verification (`tests/test_admin_api.py`)
Wrote integration tests for admin endpoints covering key creation, rotation grace periods, and unauthorized access rejection.

### Day 116 : Wiring PriorityRequestQueue for In-Flight Load Shedding
Integrated PriorityRequestQueue into the middleware so free requests get shed when server concurrency exceeds capacity thresholds.

### Day 117 : Known Architectural Constraint: In-Memory Multi-Worker Queue Boundary
Noticed that the in-memory priority queue is isolated per worker process. Across multiple Uvicorn workers, total admitted concurrency scales with worker count unless moved to Redis.

---

## Follow-Up Improvements (Days 141-143)

### Day 141 : Rate Limit by Compound Key (`src/middleware/rate_limit_middleware.py`)
Added compound keys combining API key, route path, and IP address. This lets the gateway enforce both a per-key limit on a specific endpoint and a global per-IP limit simultaneously.

### Day 142 : Warm-Up & Cold-Start Behavior (`src/api/main.py`)
Separated /health (liveness) from /health/ready (readiness). A restarted worker checks Redis connectivity before accepting traffic, preventing errors during rolling deploys.

### Day 143 : Graceful Shutdown Handling (`src/middleware/rate_limit_middleware.py` & `src/api/main.py`)
Added signal handling for SIGTERM and SIGINT. When the process gets a shutdown signal, it stops taking new traffic with 503 and drains in-flight requests within a grace period. With shutdown draining and cold-start health checks verified, the system is reliable across deployments and restarts. That completes the full 143-day engineering log.
