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

- **Current Status:** Week 11 — Observability: Grafana, Logs & Tracing Complete (Docker Compose Stack, Live Grafana Dashboards, Structured JSON Logging for Loki/Promtail, OpenTelemetry Distributed Tracing & SLA Alerting Rules) ✅
- **Next Milestone:** Week 12 — Algorithm Comparison Engine (Days 67–71)

---

## ⚡ Quickstart

### 1. Run Complete Observability Stack (Docker Compose)

```bash
docker-compose up -d
```
- **RateFortress API Gateway:** `http://localhost:8000`
- **Prometheus Telemetry:** `http://localhost:9090`
- **Grafana Live Dashboards:** `http://localhost:3000` (User: `admin` / Password: `admin`)
- **Loki Log Aggregation:** `http://localhost:3100`

### 2. Setup Local Python Environment

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

### 5. Run Locust Load Testing Suite (Week 8)

```bash
python loadtests/run_load_tests.py
```

### 6. Run k6, Spike & Soak Testing Suite (Week 9)

```bash
python loadtests/run_week9_tests.py
```
