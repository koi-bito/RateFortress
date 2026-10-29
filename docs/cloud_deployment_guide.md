# RateFortress — Production Cloud Deployment Guide

This guide details the deployment of the **RateFortress** distributed rate limiting gateway and API engine into production cloud environments.

---

## 1. Cloud Architecture Overview

In production, RateFortress runs as a containerized gateway fronting upstream services or operating as an edge rate-limiting middleware:
1. **Containerized API Gateway:** Python 3.13-slim image running FastAPI with Uvicorn multi-worker concurrency.
2. **Distributed Redis Backend:** Standalone Redis 7.2 or AWS ElastiCache cluster with `volatile-lru` eviction policy for non-blocking atomicity.
3. **Telemetry & Observability:** Prometheus scrapes `/metrics` every 5 seconds, Loki aggregates structured JSON logs via Promtail, and OpenTelemetry exports distributed traces.
4. **Health Checking:** Load balancers poll `/health` every 10–15 seconds to handle zero-downtime rolling deploys.

---

## 2. Option A: Zero-Config Deployment on Render.com

RateFortress includes a declarative Infrastructure-as-Code blueprint in `render.yaml`.

### Step-by-Step Instructions:
1. Fork or push your `RateFortress` repository to GitHub.
2. Sign in to [Render.com](https://render.com) and navigate to **Blueprints**.
3. Click **New Blueprint Instance** and select your `RateFortress` repository.
4. Render will parse `render.yaml` and provision:
   - **RateFortress Web Service:** Builds directly from `Dockerfile`, exposes port 8000, and enables auto-deploy on `main` branch pushes.
   - **Managed Redis Instance:** Provisions an isolated Redis database within the private VPC, auto-populating `REDIS_HOST` and `REDIS_PORT`.
5. Click **Apply**. Once deployment completes, your live gateway is accessible at:
   ```
   https://ratefortress.onrender.com
   ```

---

## 3. Option B: Deployment on Railway.app

1. Install the Railway CLI or connect via the [Railway Dashboard](https://railway.app).
2. Click **New Project** → **Deploy from GitHub repo** → select `RateFortress`.
3. Click **Add Service** → **Database** → **Redis**.
4. In the `ratefortress` service settings:
   - Railway auto-detects `railway.json` and builds from `Dockerfile`.
   - Add environment variables:
     - `RATEFORTRESS_BACKEND`: `redis_async`
     - `REDIS_HOST`: `${{Redis.REDISHOST}}`
     - `REDIS_PORT`: `${{Redis.REDISPORT}}`
     - `REDIS_PASSWORD`: `${{Redis.REDISPASSWORD}}`
     - `USE_FAKE_REDIS`: `false`
     - `LOG_FORMAT`: `json`
5. Railway provides an automatic HTTPS subdomain (e.g., `ratefortress-production.up.railway.app`).

---

## 4. Option C: Production Deployment on AWS EC2

For enterprise deployments requiring dedicated compute, custom VPCs, or AWS ElastiCache:

### 1. Launch EC2 Instance
- **AMI:** Ubuntu Server 24.04 LTS (HVM), SSD Volume Type
- **Instance Type:** `t3.medium` or `c6i.large` (2-4 vCPUs, 4-8 GB RAM)
- **Security Group:**
  - Inbound HTTP (80) & HTTPS (443) from `0.0.0.0/0`
  - Inbound SSH (22) from your IP only
  - Internal VPC traffic only on port 6379 (Redis)

### 2. Install Docker & Docker Compose
```bash
sudo apt update && sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu
```

### 3. Clone Repository and Start Service
```bash
git clone https://github.com/<your-username>/RateFortress.git /opt/ratefortress
cd /opt/ratefortress

# Start entire stack (Gateway + Redis + Prometheus + Grafana + Loki)
sudo docker compose up -d
```

### 4. Configure Systemd Service for Auto-Restart on Host Reboot
Create `/etc/systemd/system/ratefortress.service`:
```ini
[Unit]
Description=RateFortress Gateway Stack
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/ratefortress
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```
Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ratefortress.service
```

### 5. Nginx Reverse Proxy with Let's Encrypt SSL/TLS
```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```
Configure `/etc/nginx/sites-available/ratefortress`:
```nginx
server {
    server_name ratefortress.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
Obtain free SSL certificate:
```bash
sudo ln -s /etc/nginx/sites-available/ratefortress /etc/nginx/sites-enabled/
sudo certbot --nginx -d ratefortress.yourdomain.com
```

---

## 5. Environment Variables & Secrets Reference

| Variable | Default | Production Value | Description |
| :--- | :--- | :--- | :--- |
| `RATEFORTRESS_BACKEND` | `memory` | `redis_async` | Rate limiter storage adapter engine |
| `REDIS_HOST` | `localhost` | `redis` or VPC endpoint | Hostname or IP of Redis backend |
| `REDIS_PORT` | `6379` | `6379` | TCP port for Redis backend |
| `REDIS_PASSWORD` | `None` | `<strong-secret>` | Redis authentication secret |
| `USE_FAKE_REDIS` | `false` | `false` | When false, connects to real Redis TCP server |
| `LOG_FORMAT` | `text` | `json` | Formats stdout logs as structured JSON for Loki |
| `PROMETHEUS_MULTIPROC_DIR` | `/tmp/prometheus_multiproc` | `/tmp/prometheus_multiproc` | Multi-worker Prometheus shared metrics registry |

---

## 6. Smoke Testing the Live Deployment

Once deployed, verify your public endpoint using the provided verification script:
```bash
python scripts/smoke_test_deployment.py --url https://your-ratefortress-domain.com
```
All endpoints (`/health`, `/metrics`, `/compare`, and rate-limiting enforcement on `/api/test`) will be verified in under 5 seconds.

