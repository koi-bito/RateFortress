FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specifications and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code, templates, and configurations
COPY src/ src/
COPY monitoring/ monitoring/
COPY templates/ templates/
COPY docs/ docs/

# Ensure logs directory and multiprocess metrics directory exist
RUN mkdir -p logs /tmp/prometheus_multiproc && chmod 777 /tmp/prometheus_multiproc
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc

EXPOSE 8000

# Container healthcheck targeting /health endpoint
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["sh", "-c", "rm -rf /tmp/prometheus_multiproc/* && exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 2"]

