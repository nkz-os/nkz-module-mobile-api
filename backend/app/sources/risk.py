"""Thin client for the risk upstream."""

import httpx

from ..config import Settings
from ..forward import Identity
from . import base
from ._util import mark_empty
from .base import SourceResult


async def active_alerts(http: httpx.AsyncClient, settings: Settings, ident: Identity) -> SourceResult:
    url = f"{settings.risk_url}/api/risk/alerts"
    res = await base.call(
        "risk.active_alerts",
        lambda: http.get(url, params={"status": "active", "limit": 200}, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
    )
    return mark_empty(res, "alerts")
