"""Thin client for the vegetation upstream."""

from datetime import date

import httpx

from ..config import Settings
from ..forward import Identity
from . import base
from ._util import mark_empty
from .base import SourceResult


async def ndvi_history(http: httpx.AsyncClient, settings: Settings, ident: Identity, urn: str, start: date, end: date) -> SourceResult:
    url = f"{settings.vegetation_url}/api/vegetation/bff/history"
    res = await base.call(
        "vegetation.ndvi_history",
        lambda: http.get(url, params={"entity_id": urn, "index_type": "NDVI", "start": start.isoformat(), "end": end.isoformat()}, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
        rid=ident.request_id,
    )
    return mark_empty(res, "points")
