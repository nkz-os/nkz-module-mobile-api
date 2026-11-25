"""Per-tenant caches: in-memory TTLCache and Redis-backed SWRCache with singleflight refresh.

Stores composed responses only, never identities.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from .config import Settings

logger = logging.getLogger(__name__)


class TTLCache:
    def __init__(self, ttl_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._items: dict[tuple[str, str], tuple[float, Any]] = {}

    def get(self, tenant_id: str, key: str) -> Any | None:
        entry = self._items.get((tenant_id, key))
        if entry is None:
            return None
        expires, value = entry
        if self._clock() >= expires:
            self._items.pop((tenant_id, key), None)
            return None
        return value

    def set(self, tenant_id: str, key: str, value: Any) -> None:
        now = self._clock()
        if len(self._items) > 1024:  # opportunistic sweep keeps memory bounded
            self._items = {k: v for k, v in self._items.items() if v[0] > now}
        self._items[(tenant_id, key)] = (now + self._ttl, value)


@dataclass(frozen=True)
class SWRHit:
    status: Literal["fresh", "stale", "miss"]
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class _SWREntry:
    payload: dict[str, Any]
    fresh_until: float
    stale_until: float


def make_redis_client(settings: Settings) -> Any | None:
    """Create an async Redis client when REDIS_URL is configured; fail-open on errors."""
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as aioredis

        return aioredis.from_url(
            settings.redis_url,
            password=settings.redis_password or None,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
    except Exception as exc:  # noqa: BLE001 - fail-open to in-memory cache
        logger.warning("redis client init failed, falling back to in-memory SWR cache: %s", type(exc).__name__)
        return None


class SWRCache:
    """Stale-while-revalidate cache keyed by (tenant_id, endpoint_key) with singleflight refresh.

    Uses Redis when configured with an in-memory fallback, failing open on Redis errors.
    """

    def __init__(
        self,
        fresh_ttl_s: float,
        stale_ttl_s: float,
        *,
        redis_client: Any | None = None,
        key_prefix: str = "mobile_api:swr:",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._fresh_ttl = max(0.0, float(fresh_ttl_s))
        self._stale_ttl = max(0.0, float(stale_ttl_s))
        self._redis = redis_client
        self._prefix = key_prefix
        self._clock = clock
        self._items: dict[tuple[str, str], _SWREntry] = {}
        self._inflight: dict[tuple[str, str], asyncio.Task[Any]] = {}

    def _rkey(self, tenant_id: str, key: str) -> str:
        return f"{self._prefix}{tenant_id}:{key}"

    def _classify(self, entry: _SWREntry, now: float) -> SWRHit:
        if now < entry.fresh_until:
            return SWRHit("fresh", entry.payload)
        if now < entry.stale_until:
            return SWRHit("stale", entry.payload)
        return SWRHit("miss", None)

    def _get_memory(self, tenant_id: str, key: str, now: float) -> SWRHit:
        entry = self._items.get((tenant_id, key))
        if entry is None:
            return SWRHit("miss", None)
        hit = self._classify(entry, now)
        if hit.status == "miss":
            self._items.pop((tenant_id, key), None)
        return hit

    def _set_memory(self, tenant_id: str, key: str, entry: _SWREntry, now: float) -> None:
        if len(self._items) > 1024:
            self._items = {k: v for k, v in self._items.items() if v.stale_until > now}
        self._items[(tenant_id, key)] = entry

    async def get(self, tenant_id: str, key: str) -> SWRHit:
        now = self._clock()
        if self._redis is not None:
            try:
                raw = await self._redis.get(self._rkey(tenant_id, key))
            except Exception as exc:  # noqa: BLE001 - fail-open to in-memory
                logger.warning("swr redis get failed tenant=%s key=%s err=%s", tenant_id, key, type(exc).__name__)
                return self._get_memory(tenant_id, key, now)
            if raw is None:
                return SWRHit("miss", None)
            try:
                parsed = json.loads(raw)
                entry = _SWREntry(
                    payload=parsed["payload"],
                    fresh_until=float(parsed["fresh_until"]),
                    stale_until=float(parsed["stale_until"]),
                )
            except (ValueError, KeyError, TypeError):
                logger.warning("swr redis malformed entry tenant=%s key=%s", tenant_id, key)
                return SWRHit("miss", None)
            return self._classify(entry, now)
        return self._get_memory(tenant_id, key, now)

    async def set(self, tenant_id: str, key: str, payload: dict[str, Any]) -> None:
        now = self._clock()
        fresh_until = now + self._fresh_ttl
        stale_until = fresh_until + self._stale_ttl
        entry = _SWREntry(payload=payload, fresh_until=fresh_until, stale_until=stale_until)
        self._set_memory(tenant_id, key, entry, now)
        if self._redis is not None:
            total_ttl = max(1, int(math.ceil(self._fresh_ttl + self._stale_ttl)))
            encoded = json.dumps(
                {"payload": payload, "fresh_until": fresh_until, "stale_until": stale_until},
                separators=(",", ":"),
            )
            try:
                await self._redis.set(self._rkey(tenant_id, key), encoded, ex=total_ttl)
            except Exception as exc:  # noqa: BLE001 - fail-open, in-memory already updated
                logger.warning("swr redis set failed tenant=%s key=%s err=%s", tenant_id, key, type(exc).__name__)

    def is_refreshing(self, tenant_id: str, key: str) -> bool:
        task = self._inflight.get((tenant_id, key))
        return task is not None and not task.done()

    def trigger_refresh(
        self,
        tenant_id: str,
        key: str,
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> bool:
        """Schedule at most one in-flight background refresh per (tenant_id, key)."""
        composite = (tenant_id, key)
        existing = self._inflight.get(composite)
        if existing is not None and not existing.done():
            return False

        async def _runner() -> None:
            try:
                await coro_factory()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - background refresh must never crash loop
                logger.exception("swr refresh failed tenant=%s key=%s", tenant_id, key)
            finally:
                if self._inflight.get(composite) is task:
                    self._inflight.pop(composite, None)

        task = asyncio.create_task(_runner())
        self._inflight[composite] = task
        return True

    async def wait_inflight(self, tenant_id: str | None = None, key: str | None = None) -> None:
        """Await in-flight refresh task(s). Primarily useful in tests."""
        if tenant_id is not None and key is not None:
            task = self._inflight.get((tenant_id, key))
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            return
        tasks = list(self._inflight.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def aclose(self) -> None:
        tasks = [t for t in self._inflight.values() if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
