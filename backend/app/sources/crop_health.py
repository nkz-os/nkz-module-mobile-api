"""Thin client for the crop_health upstream."""

import httpx

from ..config import Settings
from ..forward import Identity
from . import base
from ._util import mark_empty
from .base import SourceResult


async def latest(http: httpx.AsyncClient, settings: Settings, ident: Identity, parcel_short: str) -> SourceResult:
    url = f"{settings.crop_health_url}/api/crop-health/assessments/latest"
    res = await base.call(
        "crop_health.latest",
        lambda: http.get(url, params={"parcelId": parcel_short}, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
        rid=ident.request_id,
    )
    return mark_empty(res, "assessments")


async def parcels(http: httpx.AsyncClient, settings: Settings, ident: Identity) -> SourceResult:
    url = f"{settings.crop_health_url}/api/crop-health/parcels"
    res = await base.call(
        "crop_health.parcels",
        lambda: http.get(url, headers=ident.headers),
        timeout_s=settings.source_timeout_parcels_s,
        tenant=ident.tenant_id,
        rid=ident.request_id,
    )
    return mark_empty(res, "parcels")


async def diseases_active(http: httpx.AsyncClient, settings: Settings, ident: Identity, parcel_short: str) -> SourceResult:
    url = f"{settings.crop_health_url}/api/crop-health/diseases/active"
    res = await base.call(
        "crop_health.diseases_active",
        lambda: http.get(url, params={"parcelId": parcel_short}, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
        rid=ident.request_id,
    )
    return mark_empty(res, "risks")


async def phenology(http: httpx.AsyncClient, settings: Settings, ident: Identity, parcel_urn: str) -> SourceResult:
    url = f"{settings.crop_health_url}/api/crop-health/parcels/{parcel_urn}/phenology-status"
    res = await base.call(
        "crop_health.phenology",
        lambda: http.get(url, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
        rid=ident.request_id,
    )
    return res


async def history(http: httpx.AsyncClient, settings: Settings, ident: Identity, parcel_short: str, days: int) -> SourceResult:
    url = f"{settings.crop_health_url}/api/crop-health/assessments/history"
    res = await base.call(
        "crop_health.history",
        lambda: http.get(url, params={"parcelId": parcel_short, "days": days}, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
        rid=ident.request_id,
    )
    return mark_empty(res, "points")


async def yield_forecast(http: httpx.AsyncClient, settings: Settings, ident: Identity, parcel_urn: str) -> SourceResult:
    url = f"{settings.crop_health_url}/api/crop-health/parcels/{parcel_urn}/yield-forecast"
    res = await base.call(
        "crop_health.yield_forecast",
        lambda: http.get(url, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
        rid=ident.request_id,
    )
    return res
