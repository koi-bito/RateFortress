# RateFortress : Development Plan & Milestone Log

Scope: 143 days.

RateFortress implements and benchmarks six rate limiting algorithms from scratch, progressing from pure in-memory Python structures to an async Redis backend with FastAPI middleware, Prometheus observability, administrative key management, and operational safeguards.

---

## Week 0 : Foundations (Days 1-5)

### Day 1 : What Is Rate Limiting & Why It Exists
I researched why production APIs need rate limiting, focusing on abuse prevention, credential stuffing attacks, and noisy neighbor isolation. I reviewed how major cloud providers, GitHub, and OpenAI document their quotas across requests, tokens, and concurrency limits to understand common industry patterns.

### Day 2 : The Five Core Algorithms (Conceptual)
I broke down the mechanics and primary weaknesses of Fixed Window, Sliding Window Log, Sliding Window Counter, Token Bucket, and Leaky Bucket. I compared how each behaves under bursty traffic, noting why Token Bucket fits payments APIs while Sliding Window Counter suits high-volume endpoints like search.

### Day 3 : DSA Building Blocks: Hashmaps, Deques & Circular Buffers
I reviewed Python data structures to see which would hold up under high throughput. I tested collections.deque versus standard lists for popping expired timestamps from the front, confirming that deque gives O(1) amortized pops while list pop(0) degrades to O(n).

### Day 4 : DSA Building Blocks: Heaps & Hashing for Distribution
I looked at min-heaps for priority scheduling and consistent hashing concepts for distributing keys across storage nodes. I verified that heaps provide O(log n) insertions, making them a sensible choice for ordered request queues under load.

### Day 5 : Manual Simulation, Real-World Cases & Project Scoping
I ran manual pen-and-paper simulations of boundary bursts right at the edge of fixed windows. I saw how sending requests right before and after the reset boundary lets double the nominal quota slip through, establishing the boundary leak problem I wanted to benchmark.

---

## Week 1 : Environment Setup & Project Scaffold (Days 6-10)

### Day 6 : Python Environment & Project Structure
I organized the repo into separate directories for algorithms, middleware, storage, api, and tests. Keeping pure algorithmic code decoupled from web frameworks made it much easier to write isolated unit tests without spinning up an ASGI server.

### Day 7 : GitHub Repo & Git Workflow
I initialized the git repository and established consistent commit prefixes like feat, test, refactor, and fix. I also set up basic repository files and gitignore rules to keep build artifacts and virtualenvs out of source control.

### Day 8 : Testing Framework (pytest) Setup
I configured pytest and pytest-asyncio to handle unit and concurrency tests. I adopted a test-first approach for algorithm limits, defining test cases for limit minus one, exact limit, limit plus one, and window rollover.

### Day 9 : Benchmarking Harness Skeleton
I wrote an initial benchmarking script to measure execution time, memory overhead, and throughput across synthetic client traffic. Building a single common runner meant I could compare algorithms fairly without changing the workload between runs.

### Day 10 : Week 0 and 1 Review
I reviewed the initial scaffolding, confirmed all initial tests passed cleanly, and drafted the first version of the README. Having the harness in place gave me a solid baseline before writing the first limiter.

---

## Week 2 : Fixed Window & Sliding Window Log (Days 11-15)

### Day 11 : Implement Fixed Window Counter
I implemented Fixed Window Counter using a standard dictionary to store request counts keyed by the floor of the current timestamp. The lookup and increment are constant time, but the code remains vulnerable to traffic spikes that straddle the window boundary.

### Day 12 : Test & Benchmark Fixed Window Counter
I added unit tests checking quota exhaustion and window rollovers. In pure Python, the in-memory counter clocked around 2.8 million requests per second, giving a baseline for raw CPU overhead before adding network calls.

### Day 13 : Implement Sliding Window Log
I built Sliding Window Log using collections.deque to track exact request timestamps per client. By popping timestamps older than the window length on every call, it guarantees zero boundary leaks at the cost of unbounded memory growth per client.

### Day 14 : Test & Benchmark Sliding Window Log
I wrote tests verifying that the log purges old timestamps correctly when time advances. The Python implementation reached roughly 3.4 million requests per second in-memory, though memory grew proportionally with request volume.

### Day 15 : Compare Fixed Window vs Sliding Window Log
I wrote a dedicated script to reproduce the window boundary issue directly. Fixed Window admitted 10 out of 10 requests sent across the boundary of a 5-request limit, while Sliding Window Log correctly dropped the second burst to enforce the quota.

---

## Week 3 : Sliding Window Counter, Token Bucket & Leaky Bucket (Days 16-21)

### Day 16 : Implement Sliding Window Counter
I implemented Sliding Window Counter using a weighted sum of the current and previous fixed window counts. It smooths out the boundary issue with constant memory overhead, storing only two integers per client instead of a list of timestamps.

### Day 17 : Implement Token Bucket
I built Token Bucket with lazy token refills calculated on each incoming request rather than using a background timer thread. This approach easily supports bursts up to bucket capacity while strictly metering the long-term consumption rate.

### Day 18 : Implement Leaky Bucket
I implemented Leaky Bucket using a water-level queue model that leaks at a constant rate over time. It completely prevents downstream traffic spikes by enforcing a strict outflow, rejecting requests whenever the queue capacity fills up.

### Day 19 : Full Benchmark Suite across All 5 Algorithms
I ran the benchmarking harness across all five in-memory algorithms with 10,000 requests. Sliding Window Log and Fixed Window had the highest throughput, while Sliding Window Counter and Token Bucket offered the most practical trade-off between memory and accuracy.

### Day 20 : DSA Practice Day: Sliding Window & Heap Problems
I practiced classic sliding window and heap problems on LeetCode to reinforce the algorithmic patterns. Working through monotonic deques and stream median heaps helped clarify how low-level pointer tracking applies to real systems.

### Day 21 : Week 2 and 3 Review
I wrapped up the core in-memory algorithm suite, verifying that all unit tests passed and documenting the initial throughput numbers. The next step was wrapping these limiters into an HTTP gateway.

---

## Week 4 : FastAPI Middleware Layer I (Days 22-27)

### Day 22 : FastAPI App Skeleton
I created the FastAPI application gateway and defined basic health and test endpoints. I configured Uvicorn as the ASGI server and added route scaffolding to test request handling and response lifecycles.

### Day 23 : Build Rate Limiting Middleware
I wrote custom Starlette ASGI middleware to intercept requests before they hit endpoint handlers. The middleware extracts the client identifier, looks up the corresponding limiter, and either forwards the request or returns an HTTP 429 response.

### Day 24 : HTTP 429 & Standard Rate Limit Headers
I implemented standard RFC headers including X-RateLimit-Limit, Remaining, Reset, and Retry-After. Setting Retry-After dynamically based on the algorithm reset time allowed clients to back off sensibly when throttled.

### Day 25 : Per-User, Per-IP, and Per-Endpoint Config
I extended the middleware configuration to support route-specific rules and multiple identifier types. This allowed setting tighter limits on expensive endpoints like search while keeping permissive limits on standard read routes.

### Day 26 : API Key Based Identity
I added an APIKeyManager to validate client identity via headers and query parameters. Valid keys map to specific tiers with configurable rate limit multipliers, falling back to client IP for anonymous traffic.

### Day 27 : DSA Practice Day: Hashing & Design Problems
I worked through system design exercises and hashmap-based caching patterns to practice O(1) state lookups. The exercises reinforced how fast lookups prevent middleware logic from adding latency to requests.

---

## Week 5 : FastAPI Middleware Layer II, Tiering, Resilience & Load Prep (Days 28-33)

### Day 28 : Tiered Rate Limits with Priority Queues
I implemented a priority request queue using a Python min-heap to handle traffic under server saturation. When active requests exceed a threshold, free-tier requests are shed with HTTP 503, preserving capacity for paid and enterprise traffic.

### Day 29 : Trie for Endpoint Prefix Matching
I built an EndpointTrie data structure to match incoming URL paths against route rules using prefix matching. This replaced linear path comparisons with O(k) lookups based on path length, handling wildcard route patterns cleanly.

### Day 30 : Integration Tests for Middleware
I wrote integration tests using Starlette TestClient to verify the full middleware chain. The tests checked header generation, tier multipliers, route overrides, and priority queue ordering under simulated contention.

### Day 31 : Manual Load Test with HTTP Bursts
I used a Python test script to fire bursts of 30 rapid requests against the middleware. The output confirmed clean transitions from HTTP 200 to HTTP 429 at the exact limit boundary, with accurate remaining quota countdowns.

### Day 32 : Circuit Breaker Pattern
I implemented a circuit breaker around storage calls with closed, open, and half-open states. If Redis or downstream storage times out repeatedly, the circuit trips open and fails open, keeping the API responsive rather than hanging client connections.

### Day 33 : Week 4 and 5 Review
I audited the middleware layer, confirming that priority queuing, trie matching, and circuit breakers worked together cleanly. With local middleware verified, I started moving state into Redis.

---

## Week 6 : Redis Backend I (Days 34-39)

### Day 34 : Redis & Docker Setup
I spun up Redis in Docker and integrated redis-py into the application storage layer. I added connection pooling and a fallback to FakeRedis so tests could run in headless environments without a running Redis server.

### Day 35 : Migrate Fixed Window to Redis
I implemented Fixed Window in Redis using atomic INCR and EXPIRE commands. Using Redis native atomicity kept the implementation simple and constant time, but it inherited the same window boundary doubling as the in-memory version.

### Day 36 : Migrate Sliding Window Counter to Redis
I migrated Sliding Window Counter to Redis by storing counts for the current and previous window keys. This reduced memory footprint compared to storing logs, though it initially required multiple Redis commands per check.

### Day 37 : Sliding Window Log via Redis Sorted Sets
I implemented Sliding Window Log in Redis using sorted sets (ZSET), storing timestamps as both the score and member. ZREMRANGEBYSCORE pruned expired entries while ZCARD evaluated current window volume.

### Day 38 : Test Redis-Backed Algorithms
I wrote unit and integration tests asserting correctness against the Redis backend. Tests verified key expiration, quota resets, and isolation between different client identifiers.

### Day 39 : DSA Practice Day: Tries & String Matching
I practiced string matching and prefix tree problems on LeetCode to solidify trie traversal logic. Refining my understanding of node children representations helped optimize the EndpointTrie lookup paths.

---

## Week 7 : Redis Backend II, Lua Scripts, Atomicity & Eviction (Days 40-45)

### Day 40 : Token Bucket via Redis & Lua Scripts
I implemented Token Bucket in Redis using an atomic Lua script executed with EVALSHA. Consolidating token math, timestamp checking, and state storage into a single script eliminated race conditions between concurrent requests.

### Day 41 : Leaky Bucket via Redis & Lua Scripts
I built a Redis Lua script for Leaky Bucket that tracks queue water level and leak calculations atomically. This ensured requests leak at an exact rate regardless of how many application instances read and write the keys.

### Day 42 : Atomicity Deep Dive & Race Condition Testing
I created a 50-thread concurrent test harness to compare non-atomic Redis pipelines against atomic Lua scripts. The non-atomic version allowed 18 to 25 requests through a limit of 10, while the Lua scripts permitted exactly 10 requests with 0% over-admission.

### Day 43 : Distributed Test: Two App Instances, Shared State
I spun up two separate gateway application instances backed by a single Redis container. Simultaneous traffic sent across both instances hit the shared quota correctly, confirming that distributed rate limiting worked across process boundaries.

### Day 44 : Key Eviction & TTL Strategy
I audited Redis TTL policies across all algorithm keys to prevent stale keys from lingering in memory indefinitely. Setting dynamic TTLs based on window lengths ensured Redis automatically evicts inactive user keys without manual cleanup jobs.

### Day 45 : Week 6 and 7 Review
I validated the full Redis test suite, confirming that all algorithms were thread-safe under concurrent load. The distributed engine was ready for serious load testing.

---

## Week 8 : Load Testing with Locust (Days 46-51)

### Day 46 : Locust Setup & First Load Test
I created a Locust load testing harness simulating realistic client request distributions. The initial run against an in-memory baseline verified that the test harness itself could generate clean HTTP traffic.

### Day 47 : Simulate 100 Concurrent Users
I ramped traffic to 100 concurrent users against the gateway, recording median latencies of roughly 2 ms. The service handled steady-state traffic without dropped connections or error spikes.

### Day 48 : Simulate 500 Concurrent Users
I tested 500 concurrent users and compared synchronous Redis against redis.asyncio. The synchronous client blocked the ASGI event loop, increasing median latency to 17 ms, while async Redis kept median latency down to 13 ms.

### Day 49 : Simulate 1000 Concurrent Users & Stress Test
I pushed concurrency to 1,000 and 1,500 users to find the single-worker breaking point. Throughput plateaued around 1,420 req/s, and p99 latency spiked as the Python process saturated its single CPU core.

### Day 50 : Document Latency & Error Rates
I compiled latency tables across all Locust runs, documenting p50, p95, and p99 distributions. I noted how queueing delay builds up once the server hits its capacity ceiling.

### Day 51 : DSA Practice Day: Queues & Concurrency Problems
I practiced concurrency and queue problems to better understand event loop backpressure and task starvation. These exercises made it clear why asynchronous I/O is necessary when handling external network sockets.

---

## Week 9 : Load Testing II (k6), Spike & Soak Testing (Days 52-56)

### Day 52 : k6 Setup & Comparison Test
I installed k6 and ported the load testing scenarios to JavaScript scripts. Running tests with k6 revealed lower client-side CPU overhead compared to Python greenlets in Locust.

### Day 53 : Locust vs k6 Comparison
I ran a head-to-head 500-user ramp comparing k6 and Locust. Both tools reported similar median latencies around 19 ms, but k6 captured tail latencies more reliably due to its lightweight Go scheduler.

### Day 54 : Spike Testing
I subjected the gateway to an instant spike from 10 to 1,500 users within 3 seconds. The operating system's TCP listen backlog filled immediately, dropping connections with TCP resets before recovering as soon as the spike subsided.

### Day 55 : Soak Testing
I ran a sustained 120-user soak test over an extended period while logging process memory with psutil. Memory usage stayed flat at approximately 4.5 MB with zero drift, confirming that Redis TTLs and async connection pools were not leaking.

### Day 56 : Finalize Benchmark Report
I consolidated all microbenchmarks, Locust runs, and k6 data into BENCHMARKS.md. Having actual numbers for throughput, latency, and memory made the architectural tradeoffs tangible.

---

## Week 10 : Observability: Prometheus (Days 57-61)

### Day 57 : Prometheus Fundamentals
I researched Prometheus metrics types, comparing Counters, Gauges, and Histograms. I planned out the metrics needed to track request decisions, rejected quotas, and limiter evaluation overhead.

### Day 58 : Instrument FastAPI with prometheus-client
I added prometheus-client to the FastAPI gateway and exposed a /metrics endpoint. The middleware was updated to record request totals and latencies labeled by route, status, tier, and algorithm.

### Day 59 : Track Request & Block Counters
I added custom metric labels to monitor client tier and rate limit outcomes. This allowed distinguishing between routine throttles and unexpected server errors in downstream dashboards.

### Day 60 : Run Prometheus Locally via Docker
I configured a Prometheus container in docker-compose.yml with a scrape configuration targeting the FastAPI gateway. Testing the scrape loop confirmed metrics were ingested reliably every few seconds.

### Day 61 : Query Metrics with PromQL
I wrote PromQL queries to calculate real-time request rates, error percentages, and p95/p99 latency quantiles. Writing these queries helped identify which metric labels added excessive cardinality.

---

## Week 11 : Observability: Grafana, Logs & Tracing (Days 62-66)

### Day 62 : Grafana Setup via Docker Compose
I provisioned Grafana inside Docker with automated datasource definitions for Prometheus. This eliminated manual UI configuration when starting the stack locally.

### Day 63 : Build Live Dashboard Panels
I created Grafana dashboard panels visualizing throughput, 429 block rates, algorithm breakdown, and latency heatmaps. Watching the dashboards update during load tests made traffic patterns obvious at a glance.

### Day 64 : Log Aggregation with Loki & Promtail
I integrated structured JSON logging into the middleware and added Loki and Promtail to the Compose stack. Logs included request IDs, client identifiers, and limiter latency, making it easy to trace individual throttled requests.

### Day 65 : Distributed Tracing with OpenTelemetry
I configured OpenTelemetry tracing to generate spans around middleware rate limit checks and Redis Lua calls. The traces showed exact latency attribution between network socket I/O and Python code execution.

### Day 66 : Alerting Rules & Observability Review
I wrote Prometheus alert rules triggering on sustained high 429 rates or elevated error percentages. Reviewing the observability stack confirmed that gateway performance was fully visible in real time.

---

## Week 12 : Algorithm Comparison Engine (Days 67-71)

### Day 67 : Design the /compare Endpoint
I designed an interactive /compare endpoint to evaluate synthetic traffic across all six algorithms simultaneously. The goal was to let users supply traffic parameters and inspect how each limiter reacts.

### Day 68 : Build the Comparison Report Generator
I implemented the comparison engine logic to run synthetic requests through each limiter under identical conditions. The generator collects allowed counts, blocked counts, execution times, and memory usage into a structured report.

### Day 69 : Document Tradeoffs
I documented the trade-offs across accuracy, memory footprint, CPU cost, and burst tolerance in docs/tradeoffs.md. Summarizing these differences made it clear why no single rate limiting algorithm fits every scenario.

### Day 70 : Fairness Simulation
I added fairness simulations to /compare, testing uniform versus skewed client request patterns. The simulation demonstrated how algorithms handle aggressive clients sharing a total pool of capacity.

### Day 71 : Polish Comparison Engine Output
I built a responsive Jinja2 HTML dashboard for /compare alongside the raw JSON output. The UI displays side-by-side comparison tables and latency graphs directly in any browser.

---

## Week 13 : Dockerization & Cloud Deployment (Days 72-76)

### Day 72 : Dockerize the FastAPI App
I authored a multi-stage Dockerfile based on python:3.13-slim, creating an unprivileged user and configuring health check instructions. The build resulted in a lightweight, self-contained container image.

### Day 73 : Docker Compose for Full Stack
I wired the entire stack into docker-compose.yml, connecting the FastAPI gateway, Redis, Prometheus, Grafana, Loki, and Promtail on a shared bridge network. Running docker-compose up brought up the full environment in one command.

### Day 74 : Choose & Set Up Cloud Host
I evaluated deployment options and prepared configuration blueprints for Render (render.yaml) and Railway (railway.json). Both platforms allowed deploying the containerized app with minimal operational overhead.

### Day 75 : Deploy & Configure Secrets/Env Vars
I deployed the service to a cloud staging environment, configuring environment variables for Redis connection strings and admin credentials. I verified that configuration overrides took effect properly.

### Day 76 : Smoke Test the Live Deployment
I wrote a deployment smoke test script in scripts/smoke_test_deployment.py to verify endpoint health, rate limit headers, and 429 enforcement against the live cloud instance. All checks passed with sub-5ms latency.

---

## Week 14 : CI/CD, Blue-Green Deploys & Rollback (Days 77-81)

### Day 77 : GitHub Actions: Run Tests on Push
I set up a GitHub Actions workflow (.github/workflows/test.yml) running pytest and linting across Python 3.11, 3.12, and 3.13. The pipeline included a live Redis service container so distributed tests ran automatically on every push.

### Day 78 : GitHub Actions: Auto-Deploy on Merge
I added deployment automation triggering after test suites passed on the main branch. The workflow builds the container and triggers the cloud platform webhook.

### Day 79 : Blue-Green Deployment
I documented the blue-green deployment process, verifying that traffic can cut over between blue and green containers without dropping active requests. This laid the groundwork for graceful connection draining.

### Day 80 : Rollback Strategy & Incident Drill
I wrote an incident response runbook in docs/runbook.md and practiced rolling back a simulated bad deploy. Having a concrete checklist of commands removed guesswork during incident recovery.

### Day 81 : CI/CD Review
I added build status badges to the README and verified that the entire test matrix passed consistently in CI. The automated delivery pipeline was stable.

---

## Week 15 : Documentation, Demo, Interview Prep & Resume Bullet (Days 82-86)

### Day 82 : Architecture Diagram
I drew the full system architecture diagram in docs/architecture.svg, showing how requests flow through FastAPI middleware, route tries, priority queues, and Redis Lua scripts.

### Day 83 : Write the README
I overhauled the README to clearly describe what RateFortress is, how the algorithms work, and how to run the benchmarks and Docker stack locally.

### Day 84 : Record Demo Video & Walkthrough Script
I wrote a walkthrough script in docs/demo_script_and_walkthrough.md covering the comparison dashboard, live throttling, and observability stack for demo purposes.

### Day 85 : Mock Interview Prep Day
I compiled common system design interview questions on distributed rate limiting into docs/interview_prep_and_defense.md, detailing key answers regarding race conditions, memory sizing, and multi-region sync.

### Day 86 : Final Polish & Resume Summary
I drafted an honest summary of what the project demonstrates: backend systems programming, distributed state management, and real-world concurrency debugging.

---

## Weeks 16-20 : Research Layer & Optional Extensions (Days 87-100)

### Day 87 : Draft the Comparative Write-Up
I started drafting an engineering article comparing the memory and latency characteristics of the six algorithms based on the benchmark numbers.

### Day 88 : Add Real Numbers & Charts to the Write-Up
I embedded benchmark tables and latency charts into docs/comparative_benchmark_article.md, focusing on why theoretical O(1) limits differ in real Redis implementations.

### Day 89 : Publish Comparative Systems Article
I formatted the article for developer platforms, organizing the findings into clean sections on boundary leaks, Redis Lua atomicity, and event loop blocking.

### Day 90 : Share & Gather Feedback
I shared the benchmark article with developer communities and reviewed technical feedback, noting questions about Redis Cluster hash tags and memory scaling.

### Day 91 : Write a Follow-Up Lessons Learned Post
I wrote docs/lessons_learned_followup.md, detailing mistakes I made during development such as using synchronous Redis clients in async routes and relying on in-memory counters across worker processes.

### Day 92 : Add a 6th Algorithm: GCRA (Generic Cell Rate Algorithm)
I implemented GCRA in Python and Redis Lua. By tracking a single theoretical arrival time (TAT) per client, it provides strict rate enforcement with only 32 bytes of state per user.

### Day 93 : Explore Redis Cluster & Sharding Conceptually
I documented Redis Cluster scaling strategies in docs/scaling.md, focusing on how hash tags route Lua scripts to keys hosted on the same cluster hash slot.

### Day 94 : Add a gRPC Alternative Interface
I created a high-throughput binary rate limiting service using Protocol Buffers and gRPC in src/grpc_service/, offering an alternative transport for microservice topologies.

### Day 95 : Package the Middleware
I packaged the rate limiting middleware into an installable distribution with pyproject.toml, documenting standalone usage in docs/package_guide.md.

### Day 96 : Security Hardening Pass
I audited the gateway for common security risks, testing IP header spoofing vulnerabilities and making sure that X-Forwarded-For headers are only trusted from known proxy CIDRs.

### Day 97 : Peer Review
I completed an architectural review in docs/peer_review.md, checking that public interfaces had clear documentation, error handling preserved state, and tests covered edge cases.

### Day 98 : Final Codebase Cleanup
I refactored redundant utility functions, kept naming conventions consistent across the storage backends, and confirmed that all automated tests passed cleanly.

### Day 99 : Capstone Walkthrough Recording Script
I prepared a structured technical walkthrough script in docs/capstone_deep_dive_script.md covering system design tradeoffs, Lua atomicity, and capacity math.

### Day 100 : Project Wrap-Up & Retrospective
I reviewed the completed 100-day core milestones, noting that having thorough tests and benchmarks made diagnosing performance regressions straightforward.

---

## Week 21 : Adversarial Testing & Abuse Simulation (Days 101-105)

### Day 101 : Research Real-World Rate Limit Bypass Techniques
I researched practical methods attackers use to circumvent rate limits, such as header spoofing, rotating client identifiers, and distributed bot attacks.

### Day 102 : Build an Attacker Simulation Script
I wrote loadtests/adversary_simulation.py to simulate adversarial traffic patterns, including randomized IP headers, rapid identity rotation, and quota boundary probing.

### Day 103 : Test & Fix Your Defenses: Trusted Proxy Validation
I implemented CIDR-based trusted proxy validation in src/middleware/trusted_proxy.py to ignore spoofed X-Forwarded-For headers from untrusted network clients.

### Day 104 : Defense in Depth: Behavioral Signals
I created a behavioral shield in src/middleware/behavioral_shield.py to detect suspicious request patterns and temporarily elevate throttling on misbehaving IPs.

### Day 105 : Red Team Report
I documented the adversary simulation results and defense mechanisms in docs/redteam_report.md, showing how trusted proxy checks eliminated header-spoofing bypasses.

---

## Week 22 : System Design Interview Mastery (Days 106-110)

### Day 106 : Capacity Planning & Back-of-the-Envelope Math
I calculated storage and bandwidth requirements for a 1-million request per second rate limiting service in docs/capacity_planning.md, determining Redis cluster node requirements and network socket overhead.

### Day 107 : Mock System Design Interview #1: Single-Region Gateway
I drafted a mock interview transcript for a single-region API gateway in docs/mock_interview_single_region.md, addressing latency SLAs, Redis memory sizing, and fail-open resilience.

### Day 108 : Mock System Design Interview #2: Multi-Region Global Topology
I documented a multi-region rate limiting design in docs/mock_interview_multi_region.md, explaining how local token leasing avoids cross-continent latency penalties on every request.

### Day 109 : Architecture Decision Record
I authored docs/ADR-001-algorithm-choice.md following the Michael Nygard format, documenting why Token Bucket and GCRA were chosen as default algorithms over Sliding Window Log.

### Day 110 : Review & Refine
I automated the capacity planning calculations in tests/test_system_design_calculations.py, verifying that memory sizing formulas pass automated test assertions.

---

## Week 23 : Multi-Tenant Admin Dashboard (Days 111-115)

### Day 111 : Design the Admin API
I designed RESTful administrative endpoints in src/api/admin.py for managing API keys, tiers, and rate multipliers, requiring a secret admin key for authentication.

### Day 112 : Persist API Keys Properly
I built RedisKeyStore in src/storage/key_store.py to persist key metadata in Redis hashes and index active keys in a Redis set, falling back to MemoryKeyStore for testing.

### Day 113 : Build the Dashboard Frontend (Part 1)
I created the initial admin dashboard HTML template in templates/admin.html, laying out sections for active key tables, quota usage, and key generation forms.

### Day 114 : Build the Dashboard Frontend (Part 2)
I added interactive features to the dashboard, including a live rate limit test console and key rotation controls that maintain old key validity during migrations.

### Day 115 : Polish & Secure the Dashboard
I completed integration tests for the admin API and dashboard in tests/test_admin_api.py, verifying that unauthenticated requests return 401 and key rotation works without downtime.

### Day 116 : Wiring PriorityRequestQueue for In-Flight Load Shedding
I integrated the PriorityRequestQueue into the middleware pipeline so lower-tier requests get shed automatically when server concurrency crosses threshold limits.

### Day 117 : In-Memory Multi-Worker Queue Boundary
I verified that the in-memory priority queue operates locally per worker process, documenting how multi-worker concurrency admission scales unless queues are centralized.

---

## Final Hardening & Operations (Days 141-143)

### Day 141 : Rate Limit by Compound Key
I implemented multi-dimensional compound keys combining client identifier, endpoint route, and IP address, allowing independent enforcement of per-key and per-IP quotas.

### Day 142 : Warm-Up & Cold-Start Behavior
I split health verification into liveness (/health) and readiness (/health/ready) checks so restarted workers verify Redis connectivity before accepting live traffic.

### Day 143 : Graceful Shutdown Handling
I added signal handlers for SIGTERM and SIGINT to stop accepting new requests with 503 and drain active in-flight requests cleanly within a grace period.
