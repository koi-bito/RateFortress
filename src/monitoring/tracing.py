"""OpenTelemetry Distributed Tracing Instrumentation for RateFortress (Week 11).

Provides distributed trace generation with custom child spans around rate limiting
evaluations and Redis Lua script executions, revealing exact latency attribution
between network I/O and application middleware logic.
"""

import contextlib
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# In-memory exporter for testing and deterministic inspection
in_memory_span_exporter = InMemorySpanExporter()
_tracer_provider: TracerProvider | None = None


def get_tracer(name: str = "ratefortress") -> trace.Tracer:
    """Returns a named tracer from the global or initialized TracerProvider."""
    return trace.get_tracer(name)


def setup_tracing(app: Any | None = None) -> TracerProvider:
    """Configures global OpenTelemetry TracerProvider and instruments FastAPI."""
    global _tracer_provider
    if _tracer_provider is None:
        resource = Resource.create(
            {
                "service.name": "ratefortress-gateway",
                "service.version": "0.1.0",
                "deployment.environment": os.getenv("ENVIRONMENT", "production"),
            }
        )
        provider = TracerProvider(resource=resource)

        # Attach in-memory exporter for test verification
        provider.add_span_processor(SimpleSpanProcessor(in_memory_span_exporter))

        # Attach console exporter if explicitly enabled
        if os.getenv("ENABLE_CONSOLE_TRACES", "").lower() in ("1", "true"):
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

        trace.set_tracer_provider(provider)
        _tracer_provider = provider

    if app is not None:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=_tracer_provider)

    return _tracer_provider


@contextlib.contextmanager
def trace_rate_limiter_evaluation(
    algorithm: str,
    client_id: str,
    tier: str,
    endpoint: str,
):
    """Context manager adding a custom child span around rate limit decision and Redis calls."""
    tracer = get_tracer("ratefortress.limiter")
    with tracer.start_as_current_span(
        f"rate_limiter.{algorithm}",
        attributes={
            "rate_limit.algorithm": algorithm,
            "client.id": client_id,
            "client.tier": tier,
            "http.target": endpoint,
        },
    ) as span:
        outcome = {"allowed": True, "remaining": -1}
        yield outcome
        span.set_attribute("rate_limit.allowed", outcome.get("allowed", True))
        if outcome.get("remaining", -1) >= 0:
            span.set_attribute("rate_limit.remaining", outcome["remaining"])
