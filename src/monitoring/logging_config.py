"""Structured JSON Logging Configuration for RateFortress (Week 11).

Provides high-performance JSON-formatted log emission for seamless ingestion into
Grafana Loki, Promtail, or Elasticsearch, enabling field-level filtering on client_id,
pricing tiers, algorithm decisions, and response status codes.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


class JSONLogFormatter(logging.Formatter):
    """Custom logging formatter that serializes LogRecord instances to JSON strings."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": "ratefortress",
            "message": record.getMessage(),
        }

        # Merge extra attributes if provided
        extra_fields = [
            "request_id",
            "client_id",
            "tier",
            "algorithm",
            "endpoint",
            "method",
            "status_code",
            "latency_ms",
            "limiter_overhead_ms",
            "retry_after",
            "remaining",
        ]
        for field in extra_fields:
            if hasattr(record, field):
                log_payload[field] = getattr(record, field)

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload, default=str)


def setup_structured_logging(
    log_level: str = "INFO",
    log_dir: str | Path | None = None,
) -> logging.Logger:
    """Configures root and application loggers to emit structured JSON logs."""
    logger = logging.getLogger("ratefortress")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.propagate = False

    # Avoid duplicate handlers on reload
    logger.handlers.clear()

    formatter = JSONLogFormatter()

    # Stream Handler (stdout / console)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # Optional File Handler for Promtail ingestion
    target_dir = Path(log_dir or os.getenv("LOG_DIR", "logs"))
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(target_dir / "ratefortress.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Could not initialize file log handler in %s: %s", target_dir, exc)

    return logger


# Global structured logger singleton
app_logger = setup_structured_logging()

