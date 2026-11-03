"""Orion-backed sources: parcel existence, current crop, field photos."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable

import httpx
from nkz_platform_sdk.crop_timeline import fetch_crop_timeline
from nkz_platform_sdk.orion import OrionClient

from ..config import get_settings
from .base import SourceResult

logger = logging.getLogger(__name__)


def _log(name: str, tenant: str, urn: str, status: str) -> None:
    logger.warning("source %s status=%s tenant=%s urn=%s", name, status, tenant, urn)


async def _guard(name: str, tenant: str, urn: str, aw: Awaitable[SourceResult]) -> SourceResult:
    """Run a source coroutine under the source timeout; nothing escapes."""
    try:
        return await asyncio.wait_for(aw, get_settings().source_timeout_s)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        _log(name, tenant, urn, "timeout")
        return SourceResult("timeout")
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            _log(name, tenant, urn, "empty")
            return SourceResult("empty")
        _log(name, tenant, urn, "failed")
        return SourceResult("failed", error=type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - boundary: nothing may escape
        _log(name, tenant, urn, "failed")
        return SourceResult("failed", error=type(exc).__name__)


async def parcel_exists(client: OrionClient, urn: str) -> SourceResult:
    async def run() -> SourceResult:
        ent = await client.get_entity(urn, options="keyValues")
        return SourceResult("ok", data=ent)

    return await _guard("orion.parcel", client.tenant_id, urn, run())


async def _variety(client: OrionClient, crop_id: str) -> str | None:
    try:
        ent = await asyncio.wait_for(
            client.get_entity(crop_id, options="keyValues"), get_settings().source_timeout_s
        )
    except Exception as exc:  # noqa: BLE001 - variety is optional, never degrades
        logger.warning("source orion.variety tenant=%s failed=%s", client.tenant_id, type(exc).__name__)
        return None
    v = ent.get("variety") if isinstance(ent, dict) else None
    return v if isinstance(v, str) and v else None


async def crop(tenant_id: str, urn: str, client: OrionClient) -> SourceResult:
    async def run() -> SourceResult:
        timeline = await fetch_crop_timeline(tenant_id, urn)
        if timeline is None:
            _log("orion.crop", tenant_id, urn, "failed")
            return SourceResult("failed", error="timeline")
        current = timeline.get("current") or {}
        crop_id = current.get("crop_id")
        variety = await _variety(client, crop_id) if crop_id else None
        return SourceResult("ok", data={"timeline": timeline, "variety": variety})

    return await _guard("orion.crop", tenant_id, urn, run())


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def photos(client: OrionClient, urn: str, since: datetime | None, limit: int) -> SourceResult:
    async def run() -> SourceResult:
        found: list[dict[str, Any]] = []
        for rel in ("hasAgriParcel", "refAgriParcel"):
            q = f'{rel}=="{urn}"'
            if since is not None:
                q += f';dateObserved>="{_iso_z(since)}"'
            rows = await client.query_entities(
                type="AgriParcelRecord", q=q, limit=limit, options="keyValues"
            )
            if rows:
                found = rows
                break
        withimg = [e for e in found if isinstance(e, dict) and e.get("imageUrl")]
        if not withimg:
            return SourceResult("empty")
        withimg.sort(key=lambda e: str(e.get("dateObserved") or ""), reverse=True)
        return SourceResult("ok", data=withimg)

    return await _guard("orion.photos", client.tenant_id, urn, run())
