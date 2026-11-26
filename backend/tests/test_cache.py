import asyncio

import pytest

from app.cache import SWRCache, TTLCache, make_redis_client
from app.config import Settings


class FakeRedis:
    """Minimal async Redis stub for unit testing SWRCache."""

    def __init__(self, *, fail_get: bool = False, fail_set: bool = False) -> None:
        self.store: dict[str, tuple[str, int | None]] = {}
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        if self.fail_get:
            raise ConnectionError("redis down")
        item = self.store.get(key)
        return item[0] if item is not None else None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.set_calls += 1
        if self.fail_set:
            raise ConnectionError("redis down")
        self.store[key] = (value, ex)


def test_ttl_and_tenant_isolation():
    t = [0.0]
    c = TTLCache(60, clock=lambda: t[0])
    c.set("a", "k", 1)
    assert c.get("a", "k") == 1 and c.get("b", "k") is None
    t[0] = 59.9
    assert c.get("a", "k") == 1
    t[0] = 60.0
    assert c.get("a", "k") is None


@pytest.mark.asyncio
async def test_swr_fresh_stale_expired_and_tenant_isolation():
    t = [1000.0]
    cache = SWRCache(fresh_ttl_s=30, stale_ttl_s=60, clock=lambda: t[0])

    assert (await cache.get("tenant-a", "today")).status == "miss"

    await cache.set("tenant-a", "today", {"v": 1})
    assert (await cache.get("tenant-b", "today")).status == "miss"

    t[0] = 1029.9
    hit = await cache.get("tenant-a", "today")
    assert hit.status == "fresh" and hit.payload == {"v": 1}

    t[0] = 1030.0
    hit = await cache.get("tenant-a", "today")
    assert hit.status == "stale" and hit.payload == {"v": 1}

    t[0] = 1089.9
    hit = await cache.get("tenant-a", "today")
    assert hit.status == "stale" and hit.payload == {"v": 1}

    t[0] = 1090.0
    hit = await cache.get("tenant-a", "today")
    assert hit.status == "miss" and hit.payload is None


@pytest.mark.asyncio
async def test_swr_singleflight_refresh():
    cache = SWRCache(fresh_ttl_s=30, stale_ttl_s=60)
    gate = asyncio.Event()
    calls = 0

    async def refresh():
        nonlocal calls
        calls += 1
        await gate.wait()

    assert cache.trigger_refresh("tenant-a", "parcels", refresh) is True
    assert cache.is_refreshing("tenant-a", "parcels") is True
    # Duplicate triggers for the same (tenant, key) are suppressed while in flight.
    assert cache.trigger_refresh("tenant-a", "parcels", refresh) is False
    assert cache.trigger_refresh("tenant-a", "parcels", refresh) is False
    # Different tenant or key runs independently.
    assert cache.trigger_refresh("tenant-b", "parcels", refresh) is True

    gate.set()
    await cache.wait_inflight()
    assert calls == 2
    assert cache.is_refreshing("tenant-a", "parcels") is False

    # After completion, a new refresh can be scheduled.
    assert cache.trigger_refresh("tenant-a", "parcels", refresh) is True
    await cache.wait_inflight()
    assert calls == 3


@pytest.mark.asyncio
async def test_swr_singleflight_recovers_after_exception():
    cache = SWRCache(fresh_ttl_s=30, stale_ttl_s=60)

    async def boom():
        raise RuntimeError("upstream exploded")

    assert cache.trigger_refresh("tenant-a", "today", boom) is True
    await cache.wait_inflight("tenant-a", "today")
    assert cache.is_refreshing("tenant-a", "today") is False


@pytest.mark.asyncio
async def test_swr_redis_backend_and_fail_open_fallback():
    t = [2000.0]
    redis = FakeRedis()
    cache = SWRCache(
        fresh_ttl_s=30,
        stale_ttl_s=120,
        redis_client=redis,
        key_prefix="test:swr:",
        clock=lambda: t[0],
    )

    await cache.set("tenant-a", "parcels", {"parcels": [1]})
    assert "test:swr:tenant-a:parcels" in redis.store
    assert redis.store["test:swr:tenant-a:parcels"][1] == 150

    hit = await cache.get("tenant-a", "parcels")
    assert hit.status == "fresh" and hit.payload == {"parcels": [1]}

    # Advance past fresh TTL into stale window: Redis still serves stale.
    t[0] = 2050.0
    hit = await cache.get("tenant-a", "parcels")
    assert hit.status == "stale" and hit.payload == {"parcels": [1]}

    # Simulate Redis outage: get fails open to in-memory copy!
    redis.fail_get = True
    hit = await cache.get("tenant-a", "parcels")
    assert hit.status == "stale" and hit.payload == {"parcels": [1]}

    # Simulate Redis write failure: set fails open and still updates in-memory.
    redis.fail_set = True
    t[0] = 2060.0
    await cache.set("tenant-a", "parcels", {"parcels": [2]})
    hit = await cache.get("tenant-a", "parcels")
    assert hit.status == "fresh" and hit.payload == {"parcels": [2]}

    # Malformed JSON in Redis fails open as miss instead of raising.
    redis.fail_get = False
    redis.store["test:swr:tenant-a:parcels"] = ("{not-json", 60)
    hit = await cache.get("tenant-a", "parcels")
    assert hit.status == "miss" and hit.payload is None


def test_make_redis_client_empty_returns_none():
    s = Settings(_env_file=None, redis_url="")
    assert make_redis_client(s) is None
