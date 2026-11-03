"""Thin client for the soil upstream."""

import httpx

from ..config import Settings
from ..forward import Identity
from . import base
from ._util import mark_empty
from .base import SourceResult


async def summary(http: httpx.AsyncClient, settings: Settings, ident: Identity, urn: str) -> SourceResult:
    url = f"{settings.soil_url}/v1/soil/parcel/{urn}/summary"
    res = await base.call(
        "soil.summary",
        lambda: http.get(url, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
        rid=ident.request_id,
    )
    return mark_empty(res, "horizons")


async def lab_analyses(http: httpx.AsyncClient, settings: Settings, ident: Identity, urn: str) -> SourceResult:
    url = f"{settings.soil_url}/v1/soil/parcel/{urn}/lab-analyses"
    res = await base.call(
        "soil.lab_analyses",
        lambda: http.get(url, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
        rid=ident.request_id,
    )
    return mark_empty(res, "analyses")
