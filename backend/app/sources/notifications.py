"""Thin client for the notifications upstream (weekly report)."""

import httpx

from ..config import Settings
from ..forward import Identity
from . import base
from .base import SourceResult


async def weekly_report(http: httpx.AsyncClient, settings: Settings, ident: Identity,
                        lang: str) -> SourceResult:
    url = f"{settings.notifications_url}/api/notifications/weekly-report/latest"
    return await base.call(
        "notifications.weekly_report",
        lambda: http.get(url, params={"lang": lang}, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
        rid=ident.request_id,
    )
