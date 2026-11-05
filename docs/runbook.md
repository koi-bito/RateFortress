# RateFortress — Incident Response & Rollback Runbook

## 1. Incident Severity Classification

| Severity Level | Impact Description | Detection Signal | Target MTTR | Escalation |
| :--- | :--- | :--- | :--- | :--- |
| P1 — Critical | Gateway down, 100% false-positive 429 throttling on paid/enterprise tenants, Redis complete outage | RateFortressGatewayDown alert, EnterpriseTenantThrottled alert | < 5 minutes | Immediate page |
| P2 — High | Limiter decision latency > 20ms (p95), rate limit leakage under concurrent load, worker memory leak | LimiterDecisionLatencyHigh alert, elevated 5xx error rate | < 15 minutes | Platform team notified |
| P3 — Medium | Metrics scrape failure, non-critical dashboard panel error, telemetry log shipping lag | Prometheus scrape target down, Loki log lag | < 2 hours | Business hours |

---

## 2. Emergency Rollback Procedures

### Scenario: A bad deployment causes high latency or incorrect rate-limiting math.

#### Procedure A: Cloud Platform Rollback (Render / Railway)
1. On Render: Go to Dashboard -> Services -> ratefortress -> Events/Deploys. Select the previous stable deploy and click Rollback to this deploy.
2. On Railway: Go to Deployments, select the previous stable deployment, and click Redeploy.

---

#### Procedure B: Blue-Green Cutover Rollback
If running the blue-green deployment router:
1. Run the cutover script to switch traffic back to the standby instance:
   ```bash
   python scripts/blue_green_deploy.py
   ```
2. The router updates the active pointer in under 1 ms, diverting traffic from the bad instance immediately.

#### Container Shutdown & Request Drain Policy
During cutovers, orchestrators should allow active requests to finish before stopping containers:
- Configured shutdown grace period: 10.0 seconds (with 15 seconds orchestrator termination grace).
- Kubernetes pod configuration:
  ```yaml
  spec:
    terminationGracePeriodSeconds: 15
  ```
- Docker Compose configuration:
  ```yaml
  stop_grace_period: 15s
  ```
- Lifecycle flow:
  1. Traffic router flips live ingress to the standby container.
  2. Orchestrator sends SIGTERM to the old container.
  3. The old instance sets `/health/ready` to return 503 with `Retry-After: 5` for any straggler requests.
  4. Middleware runs `drain_in_flight(timeout=10.0)`, allowing current requests to complete cleanly.
  5. Container exits with code 0 once all active requests finish.

---

#### Procedure C: Docker Compose Rollback (VM)
1. SSH into the server:
   ```bash
   ssh -i ~/.ssh/id_rsa ubuntu@ratefortress-prod.yourdomain.com
   cd /opt/ratefortress
   ```
2. Check out the previous stable tag:
   ```bash
   git fetch --tags
   git checkout v-stable-1
   ```
3. Rebuild and restart the application container without restarting Redis:
   ```bash
   sudo docker compose up -d --no-deps --build ratefortress
   ```
4. Verify container status:
   ```bash
   sudo docker compose ps
   ```

---

#### Procedure D: Git Revert (CI/CD Rollback)
1. Find the bad commit hash:
   ```bash
   git log -n 5 --oneline
   ```
2. Revert the commit and push to main:
   ```bash
   git revert <bad-commit-hash> --no-edit
   git push origin main
   ```
3. GitHub Actions runs the test suite and auto-deploys the clean commit.

---

## 3. Redis Disaster Recovery & Troubleshooting

### 1. Redis Unreachable
When Redis connectivity drops or times out:
- The circuit breaker in `src/middleware/circuit_breaker.py` trips to OPEN after 5 failures.
- Checks fail open, allowing traffic through rather than returning 500 errors to users.
- Metrics record `ratefortress_circuit_breaker_state{state="open"}` and warnings are logged.

### 2. Clearing Stale or Corrupted Rate Limit Keys
If a bug generates invalid keys or bad TTLs, purge only rate limit keys without affecting other data:
```bash
redis-cli --scan --pattern "route_*" | xargs redis-cli del
redis-cli --scan --pattern "fixed_window:*" | xargs redis-cli del
redis-cli --scan --pattern "sliding_log:*" | xargs redis-cli del
redis-cli --scan --pattern "sliding_counter:*" | xargs redis-cli del
redis-cli --scan --pattern "token_bucket:*" | xargs redis-cli del
redis-cli --scan --pattern "leaky_bucket:*" | xargs redis-cli del
```

---

## 4. Post-Incident Verification Checklist

After running a rollback:
- Run smoke test:
  ```bash
  python scripts/smoke_test_deployment.py --url https://ratefortress.yourdomain.com
  ```
- Check health status:
  ```bash
  curl -I https://ratefortress.yourdomain.com/health
  ```
- Check Prometheus `/metrics` to verify scrape targets are green and latencies have normalized.
- Inspect the Grafana overview dashboard to confirm normal request rates and 429 distributions.
- Note what broke, how it was detected, and what needs fixing in tests.
