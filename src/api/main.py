"""RateFortress FastAPI Application Gateway."""

from fastapi import FastAPI

from src.middleware.rate_limit_middleware import RateLimitMiddleware

app = FastAPI(
    title="RateFortress",
    version="0.1.0",
    description="High-performance distributed rate limiter engine and API gateway.",
)

# Attach production rate limiting middleware
app.add_middleware(RateLimitMiddleware)


@app.get("/")
def root():
    """Service health and root metadata."""
    return {"status": "ok", "service": "RateFortress", "version": "0.1.0"}


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/api/test")
def test_endpoint():
    """Standard test endpoint with default rate limits."""
    return {"message": "This endpoint is protected by RateFortress."}


@app.get("/api/expensive-endpoint")
def expensive_endpoint():
    """Simulated resource-heavy endpoint with strict sliding window log limits."""
    return {
        "message": "Expensive computation or database query completed successfully."
    }
