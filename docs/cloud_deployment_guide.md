# RateFortress — Cloud Deployment Guide

These are the deployment steps I use to run RateFortress in cloud environments like Render, Railway, or a standalone Linux VM. This deployment was kept single-region by design.

---

## 1. Cloud Architecture

In production, RateFortress runs as a containerized gateway in front of upstream services:
1. API Gateway: Python 3.13-slim image running FastAPI with Uvicorn.
2. Redis Backend: Redis 7.2 or a managed Redis instance for shared state and Lua script execution.
3. Observability: Prometheus scraping /metrics, Promtail shipping JSON logs to Loki, and OpenTelemetry exporting traces.
4. Health Checking: Load balancers polling /health to handle rolling updates.

---

## 2. Option A: Deploying on Render.com

I included a blueprint file in `render.yaml`.

Steps:
1. Push the repository to GitHub.
2. Go to Render and create a New Blueprint Instance selecting this repository.
3. Render reads `render.yaml` and provisions both the Dockerfile web service on port 8000 and a private Redis instance.
4. Apply changes and wait for the build to finish.

---

## 3. Option B: Deploying on Railway.app

1. Create a new project on Railway from the GitHub repository.
2. Add a Redis database service to the project.
3. In service settings, Railway picks up `railway.json` and builds the Dockerfile.
4. Set environment variables for Redis (`RATEFORTRESS_BACKEND=redis_async`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, and `LOG_FORMAT=json`).
5. Railway assigns an HTTPS domain automatically.

---

## 4. Option C: Running on an Ubuntu VM (AWS EC2)

For running directly on a Linux VM:

### 1. Launch Instance
- OS: Ubuntu Server 24.04 LTS
- Size: t3.medium or c6i.large (2 to 4 vCPUs, 4 GB RAM)
- Ports: Inbound 80 and 443 open to traffic, port 22 open only to your IP, port 6379 restricted to localhost.

### 2. Install Docker
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

### 3. Clone and Start Stack
```bash
git clone https://github.com/koi-bito/RateFortress.git /opt/ratefortress
cd /opt/ratefortress
sudo docker compose up -d
```

### 4. Systemd Auto-Restart
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

Enable it:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ratefortress.service
```

### 5. Nginx Reverse Proxy with SSL
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

Enable site and generate certificate:
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

## 6. Smoke Testing the Deployment

Once deployed, I test the live instance with the smoke test script:
```bash
python scripts/smoke_test_deployment.py --url https://your-ratefortress-domain.com
```
It hits `/health`, `/metrics`, `/compare`, and `/api/test` to check that rate limits and headers are behaving properly.
