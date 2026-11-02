"""Tests for PriorityRequestQueue."""

import asyncio
import random

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from src.middleware.priority_queue import PriorityRequestQueue
from src.middleware.rate_limit_middleware import RateLimitMiddleware


def test_priority_ordering():
    pq = PriorityRequestQueue()
    pq.push(PriorityRequestQueue.PRIORITY_ANONYMOUS, "anon_1")
    pq.push(PriorityRequestQueue.PRIORITY_PAID, "paid_1")
    pq.push(PriorityRequestQueue.PRIORITY_ENTERPRISE, "ent_1")
    pq.push(PriorityRequestQueue.PRIORITY_FREE, "free_1")

    # Order must be enterprise -> paid -> free -> anonymous
    assert pq.pop()[2] == "ent_1"
    assert pq.pop()[2] == "paid_1"
    assert pq.pop()[2] == "free_1"
    assert pq.pop()[2] == "anon_1"
    assert pq.pop() is None


def test_fifo_ordering_for_equal_priority():
    pq = PriorityRequestQueue()
    pq.push(PriorityRequestQueue.PRIORITY_PAID, "paid_first")
    pq.push(PriorityRequestQueue.PRIORITY_PAID, "paid_second")
    pq.push(PriorityRequestQueue.PRIORITY_PAID, "paid_third")

    assert pq.pop()[2] == "paid_first"
    assert pq.pop()[2] == "paid_second"
    assert pq.pop()[2] == "paid_third"


def test_mixed_overload_simulation():
    """Simulates 50 free-tier and 50 paid-tier requests pushed in random order.

    Confirms all 50 paid requests are dequeued before any free request.
    """
    pq = PriorityRequestQueue()
    requests = []

    for i in range(50):
        requests.append((PriorityRequestQueue.PRIORITY_FREE, f"free_{i}"))
        requests.append((PriorityRequestQueue.PRIORITY_PAID, f"paid_{i}"))

    # Shuffle to simulate random interleaved arrival under load
    random.seed(42)
    random.shuffle(requests)

    for priority, req_id in requests:
        pq.push(priority, req_id)

    assert len(pq) == 100

    # Pop first 50: all must be paid
    popped_first_50 = [pq.pop() for _ in range(50)]
    for item in popped_first_50:
        assert item[0] == PriorityRequestQueue.PRIORITY_PAID
        assert item[2].startswith("paid_")

    # Pop remaining 50: all must be free
    popped_second_50 = [pq.pop() for _ in range(50)]
    for item in popped_second_50:
        assert item[0] == PriorityRequestQueue.PRIORITY_FREE
        assert item[2].startswith("free_")

    assert pq.is_empty()


@pytest.mark.asyncio
async def test_below_saturation_threshold_free_tier_passes_normally():
    """Below saturation threshold, free-tier requests pass through normally without shedding."""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, saturation_threshold=5)

    @app.get("/hello")
    def hello():
        return {"msg": "ok"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for _ in range(3):
            resp = await ac.get("/hello", headers={"X-API-Key": "key_free_abc"})
            assert resp.status_code == 200
            assert resp.headers["X-RateLimit-Tier"] == "free"
            assert "Retry-After" not in resp.headers


@pytest.mark.asyncio
async def test_saturation_sheds_free_tier_and_serves_paid_tier():
    """Under simulated saturation, free-tier requests are shed (503) while paid-tier requests

    are queued and served when capacity frees up.
    """
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        saturation_threshold=1,
        queue_timeout=2.0,
        shed_free_tier=True,
    )

    hold_event = asyncio.Event()

    @app.get("/slow")
    async def slow():
        await hold_event.wait()
        return {"status": "slow_done"}

    @app.get("/fast")
    async def fast():
        return {"status": "fast_done"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Occupy the single available slot
        task_slow = asyncio.create_task(ac.get("/slow"))
        await asyncio.sleep(0.01)

        # 2. Free-tier request under saturation must be shed immediately with 503 + Retry-After
        free_resp = await ac.get("/fast", headers={"X-API-Key": "key_free_abc"})
        assert free_resp.status_code == 503
        assert free_resp.headers["Retry-After"] == "1"
        assert free_resp.headers["X-RateLimit-Tier"] == "free"
        assert free_resp.headers["X-RateLimit-Remaining"] == "0"
        assert "service unavailable" in free_resp.json()["error"]

        # 3. Paid-tier request under saturation enters PriorityRequestQueue
        task_paid = asyncio.create_task(
            ac.get("/fast", headers={"X-API-Key": "key_paid_xyz"})
        )
        await asyncio.sleep(0.01)

        # 4. Release slow request to free up the slot
        hold_event.set()
        slow_resp = await task_slow
        assert slow_resp.status_code == 200

        # 5. Paid request is dequeued, executes, and returns 200 OK
        paid_resp = await task_paid
        assert paid_resp.status_code == 200
        assert paid_resp.headers["X-RateLimit-Tier"] == "paid"


@pytest.mark.asyncio
async def test_priority_ordering_under_saturation():
    """Higher priority requests (enterprise) jump ahead of lower priority requests (paid)

    in the PriorityRequestQueue under saturation.
    """
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        saturation_threshold=1,
        queue_timeout=2.0,
    )

    hold_event = asyncio.Event()
    order = []

    @app.get("/slow")
    async def slow():
        await hold_event.wait()
        return {"status": "slow_done"}

    @app.get("/work")
    async def work(request: Request):
        tier = request.headers.get("x-tier-tag", "unknown")
        order.append(tier)
        return {"tier": tier}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        task_slow = asyncio.create_task(ac.get("/slow"))
        await asyncio.sleep(0.01)

        # Enqueue paid request (priority 1) first
        task_paid = asyncio.create_task(
            ac.get("/work", headers={"X-API-Key": "key_paid_xyz", "x-tier-tag": "paid"})
        )
        await asyncio.sleep(0.01)

        # Enqueue enterprise request (priority 0) second
        task_ent = asyncio.create_task(
            ac.get(
                "/work",
                headers={"X-API-Key": "key_enterprise_999", "x-tier-tag": "enterprise"},
            )
        )
        await asyncio.sleep(0.01)

        # Release slow request
        hold_event.set()
        await task_slow
        await task_paid
        await task_ent

        # Enterprise must be processed before paid despite arriving second
        assert order == ["enterprise", "paid"]


@pytest.mark.asyncio
async def test_saturation_queue_depth_exceeded():
    """When PriorityRequestQueue reaches max_queue_depth, subsequent requests are shed with 503.

    Once timed-out requests expire, new requests are accepted without being blocked by dead futures.
    """
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        saturation_threshold=1,
        max_queue_depth=1,
        queue_timeout=0.1,
    )

    hold_event = asyncio.Event()

    @app.get("/slow")
    async def slow():
        await hold_event.wait()
        return {"msg": "slow"}

    @app.get("/ping")
    def ping():
        return {"msg": "pong"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        task_slow = asyncio.create_task(ac.get("/slow"))
        await asyncio.sleep(0.01)

        # 1st paid request fills the single queue slot
        task_paid1 = asyncio.create_task(
            ac.get("/ping", headers={"X-API-Key": "key_paid_xyz"})
        )
        await asyncio.sleep(0.01)

        # 2nd paid request arrives when queue is full -> immediately shed with 503
        resp_paid2 = await ac.get("/ping", headers={"X-API-Key": "key_paid_xyz"})
        assert resp_paid2.status_code == 503
        assert "queue capacity exceeded" in resp_paid2.json()["detail"]
        assert resp_paid2.headers["Retry-After"] == "1"

        # Wait for 1st request to time out
        resp_paid1 = await task_paid1
        assert resp_paid1.status_code == 503
        assert "timed out" in resp_paid1.json()["detail"]

        # 3rd request arrives after 1st timed out -> should be accepted, not shed
        task_paid3 = asyncio.create_task(
            ac.get("/ping", headers={"X-API-Key": "key_paid_xyz"})
        )
        await asyncio.sleep(0.01)

        hold_event.set()
        await task_slow
        resp3 = await task_paid3
        assert resp3.status_code == 200


@pytest.mark.asyncio
async def test_saturation_queue_timeout():
    """Queued requests exceeding queue_timeout are shed with 503 and Retry-After."""
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        saturation_threshold=1,
        queue_timeout=0.05,
    )

    hold_event = asyncio.Event()

    @app.get("/slow")
    async def slow():
        await hold_event.wait()
        return {"msg": "slow"}

    @app.get("/ping")
    def ping():
        return {"msg": "pong"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        task_slow = asyncio.create_task(ac.get("/slow"))
        await asyncio.sleep(0.01)

        # Paid request waits longer than queue_timeout (0.05s)
        resp = await ac.get("/ping", headers={"X-API-Key": "key_paid_xyz"})
        assert resp.status_code == 503
        assert "timed out waiting in priority queue" in resp.json()["detail"]
        assert resp.headers["Retry-After"] == "1"

        hold_event.set()
        await task_slow


@pytest.mark.asyncio
async def test_saturation_fifo_ordering_for_equal_priority():
    """Equal-priority requests maintain strict FIFO order when dequeued under saturation."""
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        saturation_threshold=1,
        queue_timeout=2.0,
    )

    hold_event = asyncio.Event()
    order = []

    @app.get("/slow")
    async def slow():
        await hold_event.wait()
        return {"status": "slow_done"}

    @app.get("/order")
    async def order_route(request: Request):
        tag = request.headers.get("x-tag", "")
        order.append(tag)
        return {"tag": tag}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        task_slow = asyncio.create_task(ac.get("/slow"))
        await asyncio.sleep(0.01)

        # Enqueue three paid requests in sequence: p1, p2, p3
        t1 = asyncio.create_task(
            ac.get("/order", headers={"X-API-Key": "key_paid_xyz", "x-tag": "p1"})
        )
        await asyncio.sleep(0.01)
        t2 = asyncio.create_task(
            ac.get("/order", headers={"X-API-Key": "key_paid_xyz", "x-tag": "p2"})
        )
        await asyncio.sleep(0.01)
        t3 = asyncio.create_task(
            ac.get("/order", headers={"X-API-Key": "key_paid_xyz", "x-tag": "p3"})
        )
        await asyncio.sleep(0.01)

        hold_event.set()
        await task_slow
        await t1
        await t2
        await t3

        assert order == ["p1", "p2", "p3"]
