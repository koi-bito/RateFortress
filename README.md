# RateFortress — Distributed Rate Limiting Engine

**RateFortress** is a production-grade, distributed rate limiting engine built from first principles. It supports multiple core rate limiting algorithms (Fixed Window Counter, Sliding Window Log, Sliding Window Counter, Token Bucket, and Leaky Bucket), exposed via pluggable FastAPI middleware, backed by Redis for distributed state, benchmarked under heavy concurrent load, fully observable through Prometheus and Grafana metrics, and hardened against real-world abuse vectors.

---

## 🛠️ Tech Stack

- **Languages & Frameworks:** Python 3.13+, FastAPI, Go (comparative benchmarking), Uvicorn
- **Distributed State & Storage:** Redis, Lua scripting (atomic execution)
- **Observability:** Prometheus, Grafana, Loki, OpenTelemetry
- **Load Testing & Chaos:** Locust, k6, Toxiproxy
- **Testing & Quality:** Pytest, pytest-benchmark, Ruff, Black
- **Deployment:** Docker, Docker Compose, GitHub Actions, AWS EC2 / Render

---

## 📁 Repository Structure

```
ratefortress/
├── src/
│   ├── algorithms/     # Pure algorithm implementations (Fixed Window, Sliding Window, Token Bucket, etc.)
│   ├── middleware/     # FastAPI / Starlette middleware integration
│   ├── api/            # API endpoints & gateway routing
│   └── storage/        # Storage adapters (In-Memory, Redis client, Lua scripts)
├── tests/              # Unit, integration, and property tests
├── benchmarks/         # Algorithm & middleware benchmark harness
├── loadtests/          # Locust & k6 distributed load testing scripts
├── monitoring/         # Prometheus & Grafana dashboard configurations
├── docs/               # Architecture decision records (ADRs) & system design specs
├── requirements.txt    # Project dependencies
├── LEARNINGS.md        # Daily engineering logs and DSA trade-off notes
├── BENCHMARKS.md       # Empirical benchmark results and comparative analysis
└── building_plan.md    # 29-week comprehensive roadmap & milestones
```

---

## 🚦 Status & Milestones

- **Current Status:** Week 4 — FastAPI Middleware Layer I Complete (HTTP 429, Headers, Tiers & Key Extractors) ✅
- **Next Milestone:** Week 5 — FastAPI Middleware Layer II (Tiering, Priority Queues, Trie Route Matching & Fail-Open Resilience)

---

## ⚡ Quickstart

### 1. Setup Virtual Environment

```bash
# Windows
python -m venv ratefortress_env
ratefortress_env\Scripts\activate

# Linux / macOS
python3 -m venv ratefortress_env
source ratefortress_env/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Tests

```bash
pytest -v
```

### 4. Run Benchmark Harness

```bash
python benchmarks/run_benchmark.py
```
