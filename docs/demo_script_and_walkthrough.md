# RateFortress — Demo Video Script & Walkthrough Notes

These are my speaking notes for recording a quick 2.5-minute video walkthrough of RateFortress.

---

## 1. Video Demo Script (2.5 Minutes)

### [0:00 to 0:30] Introduction & High-Level Architecture
- Visual: Show docs/architecture.svg.
- Spoken Script:
  "Hi, I am showing RateFortress, a distributed rate limiting engine and gateway I built in Python and Redis.

  Most rate limiters in tutorials are simple fixed-window counters that suffer from boundary bursts and race conditions. I implemented five core algorithms from scratch: Fixed Window, Sliding Window Log, Sliding Window Counter, Token Bucket, and Leaky Bucket.

  I exposed them through FastAPI middleware backed by Redis with atomic Lua scripts to prevent race conditions, wired up Prometheus and Grafana dashboards, and added tests for zero-downtime cutovers."

---

### [0:30 to 1:15] Algorithm Comparison Engine
- Visual: Open browser to http://localhost:8000/compare.
- Spoken Script:
  "To compare these algorithms under identical conditions, I built an interactive endpoint at /compare.

  It fires identical synthetic traffic across all algorithms using an isolated virtual clock.

  When I change the traffic pattern from uniform to skewed, where 20% of users send rapid bursts, Token Bucket lets the bursty clients through because it accumulates tokens during idle periods. Leaky Bucket drops the overflow to force a smooth, steady outflow. Sliding Window Counter enforces strict rolling quotas without leaking across boundaries."

---

### [1:15 to 1:55] Observability & Load Testing
- Visual: Split screen with terminal running Locust on the left and Grafana on the right.
- Spoken Script:
  "Here is the observability setup under a 500-user concurrent load test in Locust.

  The first panel separates allowed traffic from 429 throttled requests.

  The latency panel tracks p95 and p99 times, while another panel isolates the rate limiter decision overhead, showing that the Redis Lua scripts complete each evaluation in under 150 microseconds.

  Logs are formatted as structured JSON for Loki, and OpenTelemetry traces capture latency across middleware spans."

---

### [1:55 to 2:30] Deployment & Rollback Drill
- Visual: Show passing GitHub Actions workflows and run scripts/blue_green_deploy.py.
- Spoken Script:
  "The application is packaged with Docker, configured with blueprints for cloud hosting, and tested across Python 3.11, 3.12, and 3.13 against a live Redis service.

  I also tested cutovers between blue and green instances so traffic switches over without dropping requests mid-flight, and wrote down an incident runbook for rollbacks.

  The whole project is open source on GitHub with benchmarks and daily logs."

---

## 2. Project Summary Post Draft (LinkedIn & Technical Community Launch Post)

I built RateFortress from scratch to explore distributed rate limiting without relying on third-party black boxes.

Most basic implementations use simple Redis INCR calls, which run into two common issues:
1. Window boundary bursts: Fixed window counters allow double the quota if requests land right across the reset boundary.
2. Check-and-set race conditions: Under concurrency, separate read and write steps let excess requests pass before counts update.

To address these, I built:
- Core algorithms: Fixed Window, Sliding Window Log, Sliding Window Counter, Token Bucket, and Leaky Bucket.
- Atomic Lua scripts: Moving the check and update into Redis eliminated race conditions under high concurrency.
- Comparison engine: A live /compare endpoint to test how each algorithm handles steady versus bursty traffic.
- Observability: Prometheus metrics, Grafana dashboards, Loki structured logging, and OpenTelemetry tracing.
- Operational testing: Automated tests in GitHub Actions and zero-downtime cutover scripts.

The benchmarks and daily logs are in the repository:
GitHub: https://github.com/koi-bito/RateFortress
Benchmark Report: https://github.com/koi-bito/RateFortress/blob/main/BENCHMARKS.md
