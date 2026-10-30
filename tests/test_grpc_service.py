"""Integration tests for the RateFortress gRPC service (Day 94)."""

import grpc
import pytest

from src.grpc_service import ratefortress_pb2, ratefortress_pb2_grpc
from src.grpc_service.service import create_grpc_server


@pytest.fixture(scope="module")
def grpc_server_and_stub():
    """Starts an ephemeral gRPC server and provides a client stub."""
    server, port = create_grpc_server(host="127.0.0.1", port=0, default_algorithm="token_bucket")
    server.start()

    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    stub = ratefortress_pb2_grpc.RateLimiterStub(channel)

    yield stub

    channel.close()
    server.stop(grace=None)


def test_grpc_check_rate_limit_allows_then_blocks(grpc_server_and_stub):
    """Validates that a client can burst up to limit and is throttled on overflow."""
    stub = grpc_server_and_stub
    client_id = "grpc_user_1"
    endpoint = "/api/test"  # base limit 10

    # 10 requests allowed
    for i in range(10):
        req = ratefortress_pb2.RateLimitRequest(
            client_id=client_id,
            endpoint=endpoint,
            tier="free",
            algorithm="token_bucket",
            cost=1,
        )
        resp = stub.CheckRateLimit(req)
        assert resp.allowed is True, f"Request {i+1} should have been allowed"
        assert resp.limit == 10

    # 11th request throttled
    req = ratefortress_pb2.RateLimitRequest(
        client_id=client_id,
        endpoint=endpoint,
        tier="free",
        algorithm="token_bucket",
        cost=1,
    )
    resp = stub.CheckRateLimit(req)
    assert resp.allowed is False
    assert resp.remaining == 0
    assert resp.retry_after_seconds >= 1


def test_grpc_gcra_algorithm_selection(grpc_server_and_stub):
    """Validates GCRA algorithm execution over gRPC."""
    stub = grpc_server_and_stub
    client_id = "grpc_gcra_user"
    endpoint = "/api/test"

    for _ in range(10):
        req = ratefortress_pb2.RateLimitRequest(
            client_id=client_id,
            endpoint=endpoint,
            tier="free",
            algorithm="gcra",
            cost=1,
        )
        resp = stub.CheckRateLimit(req)
        assert resp.allowed is True

    # Next request blocked
    req = ratefortress_pb2.RateLimitRequest(
        client_id=client_id,
        endpoint=endpoint,
        tier="free",
        algorithm="gcra",
        cost=1,
    )
    resp = stub.CheckRateLimit(req)
    assert resp.allowed is False


def test_grpc_tier_multiplier(grpc_server_and_stub):
    """Validates that Paid tier receives a 10x limit multiplier."""
    stub = grpc_server_and_stub
    client_id = "grpc_paid_user"
    endpoint = "/api/test"

    req = ratefortress_pb2.RateLimitRequest(
        client_id=client_id,
        endpoint=endpoint,
        tier="paid",
        algorithm="token_bucket",
        cost=1,
    )
    resp = stub.CheckRateLimit(req)
    assert resp.allowed is True
    assert resp.limit == 100  # 10 * 10x


def test_grpc_get_quota(grpc_server_and_stub):
    """Validates Quota inspection RPC."""
    stub = grpc_server_and_stub
    req = ratefortress_pb2.QuotaRequest(
        client_id="new_user_quota",
        endpoint="/api/test",
        algorithm="token_bucket",
    )
    resp = stub.GetQuota(req)
    assert resp.limit == 10
    assert resp.remaining == 10
