"""Thin client for the field_ops upstream."""

import httpx

from ..config import Settings
from ..forward import Identity
from . import base
from ._util import mark_empty
from .base import SourceResult


async def operations(http: httpx.AsyncClient, settings: Settings, ident: Identity, urn: str, limit: int = 100) -> SourceResult:
    url = f"{settings.field_ops_url}/api/field-operations/operations"
    res = await base.call(
        "field_ops.operations",
        lambda: http.get(url, params={"parcel_id": urn, "limit": limit}, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
    )
    return mark_empty(res, "operations")
