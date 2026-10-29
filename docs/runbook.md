# RateFortress — Production Incident Response & Rollback Runbook

This runbook defines the emergency response protocol, severity levels, rapid rollback procedures, and disaster recovery steps for the **RateFortress** distributed rate limiting infrastructure.

---

## 1. Incident Severity Classification

| Severity Level | Impact Description | Detection Signal | Target MTTR | Escalation |
| :--- | :--- | :--- | :--- | :--- |
| **P1 — Critical** | Gateway down, 100% false-positive 429 throttling on paid/enterprise tenants, Redis complete outage | `RateFortressGatewayDown` alert, `EnterpriseTenantThrottled` alert | **< 5 minutes** | On-call engineer paged immediately |
| **P2 — High** | Limiter decision latency > 20ms (p95), rate limit leakage under concurrent load, worker memory leak | `LimiterDecisionLatencyHigh` alert, elevated 5xx error rate | **< 15 minutes** | Platform team notified |
| **P3 — Medium** | Metrics scrape failure, non-critical dashboard panel error, telemetry log shipping lag | Prometheus scrape target down, Loki log lag | **< 2 hours** | Addressed during business hours |

---

## 2. Emergency Rollback Procedures

### Scenario: A bad deployment introduces faulty rate-limiting math or high latency.

#### Procedure A: Cloud Platform Instant Rollback (Render / Railway)
1. **Render.com:**
   - Navigate to **Dashboard** → **Services** → `ratefortress`.
   - Click the **Events** / **Deploys** tab.
   - Locate the previous known-good deployment (e.g., `v-stable-1`).
   - Click the three dots `...` and select **Rollback to this deploy**.
   - Render instantly switches the HTTP routing proxy to the previous container image without rebuilding.
2. **Railway.app:**
   - Navigate to `ratefortress` project → **Deployments**.
   - Select the previous stable deployment → **Redeploy**.

---

#### Procedure B: Blue-Green Cutover Rollback (Zero-Downtime Router)
If operating a Blue-Green deployment with a traffic router:
1. Run the instant cutover switch back to the standby Blue environment:
   ```bash
   python scripts/blue_green_deploy.py
   ```
2. The router atomically updates the active environment pointer in $< 1\text{ ms}$, terminating bad traffic immediately.

---

#### Procedure C: Docker Compose Rollback (EC2 / Bare Metal)
1. SSH into the production host:
   ```bash
   ssh -i ~/.ssh/id_rsa ubuntu@ratefortress-prod.yourdomain.com
   cd /opt/ratefortress
   ```
2. Revert to the previous stable release tag:
   ```bash
   git fetch --tags
   git checkout v-stable-1
   ```
3. Restart the application container with zero downtime for Redis:
   ```bash
   sudo docker compose up -d --no-deps --build ratefortress
   ```
4. Verify container status:
   ```bash
   sudo docker compose ps
   ```

---

#### Procedure D: Git Revert (CI/CD Pipeline Rollback)
1. Identify the offending commit hash:
   ```bash
   git log -n 5 --oneline
   ```
2. Revert the commit and push directly to `main`:
   ```bash
   git revert <bad-commit-hash> --no-edit
   git push origin main
   ```
3. GitHub Actions CI/CD pipeline triggers automated tests and auto-deploys the clean commit.

---

## 3. Redis Disaster Recovery & Split-Brain Mitigation

### 1. Redis Failure / Unreachable Backend
- **Fail-Open Circuit Breaker:**
  RateFortress includes a built-in `CircuitBreaker` in `src/middleware/circuit_breaker.py`. When Redis connectivity fails or times out:
  - The circuit trips to **OPEN**.
  - All rate limiter checks safely **fail-open** (allow traffic to proceed rather than returning 500 errors).
  - Metrics record `ratefortress_circuit_breaker_state{state="open"}`.
  - Paying customers experience zero downtime while engineers restore Redis.

### 2. Purging Corrupted or Stale Rate Limit Keys
If bad code populated erroneous quotas or corrupted TTL values, purge only transient rate limiting keys without impacting permanent tenant settings:
```bash
# Connect to Redis CLI
redis-cli -h $REDIS_HOST -p $REDIS_PORT

# Safely evict transient rate limiting keys by pattern
redis-cli --scan --pattern "route_*" | xargs redis-cli del
redis-cli --scan --pattern "fixed_window:*" | xargs redis-cli del
redis-cli --scan --pattern "sliding_log:*" | xargs redis-cli del
redis-cli --scan --pattern "sliding_counter:*" | xargs redis-cli del
redis-cli --scan --pattern "token_bucket:*" | xargs redis-cli del
redis-cli --scan --pattern "leaky_bucket:*" | xargs redis-cli del
```

---

## 4. Post-Incident Verification Checklist

After executing any rollback or disaster recovery procedure:

- [ ] **Run Live Smoke Test:**
  ```bash
  python scripts/smoke_test_deployment.py --url https://ratefortress.yourdomain.com
  ```
- [ ] **Confirm /health returns 200 OK:**
  ```bash
  curl -I https://ratefortress.yourdomain.com/health
  ```
- [ ] **Verify Prometheus Telemetry:**
  Confirm Prometheus is actively scraping `/metrics` and latency quantiles (p50, p95, p99) return to nominal sub-millisecond levels.
- [ ] **Verify Grafana Dashboard:**
  Inspect the `RateFortress Overview` dashboard for normal throughput curves (HTTP 200 vs. nominal 429 drops).
- [ ] **Document Postmortem:**
  Record timeline, root cause, blast radius, time to rollback, and preventative engineering changes.

