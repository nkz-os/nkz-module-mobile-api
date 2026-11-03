"""Thin client for the weather upstream."""

from datetime import date

import httpx

from ..config import Settings
from ..forward import Identity
from . import base
from ._util import mark_empty
from .base import SourceResult


async def agro_status(http: httpx.AsyncClient, settings: Settings, ident: Identity, urn: str) -> SourceResult:
    url = f"{settings.weather_api_url}/api/weather/parcel/{urn}/agro-status"
    res = await base.call(
        "weather.agro_status",
        lambda: http.get(url, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
    )
    return res


async def forecast(http: httpx.AsyncClient, settings: Settings, ident: Identity, urn: str, days: int = 3) -> SourceResult:
    url = f"{settings.weather_api_url}/api/weather/parcel/{urn}/forecast"
    res = await base.call(
        "weather.forecast",
        lambda: http.get(url, params={"days": days}, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
    )
    return mark_empty(res, "forecast")


async def parcel_alerts(http: httpx.AsyncClient, settings: Settings, ident: Identity, urn: str) -> SourceResult:
    url = f"{settings.weather_api_url}/api/weather/parcel/{urn}/alerts"
    res = await base.call(
        "weather.parcel_alerts",
        lambda: http.get(url, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
    )
    return mark_empty(res, "alerts")


async def tenant_alerts(http: httpx.AsyncClient, settings: Settings, ident: Identity) -> SourceResult:
    url = f"{settings.weather_api_url}/api/weather/alerts"
    res = await base.call(
        "weather.tenant_alerts",
        lambda: http.get(url, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
    )
    return mark_empty(res, "alerts")


async def daily(http: httpx.AsyncClient, settings: Settings, ident: Identity, urn: str, start: date, end: date) -> SourceResult:
    url = f"{settings.weather_api_url}/api/weather/parcel/{urn}/daily"
    res = await base.call(
        "weather.daily",
        lambda: http.get(url, params={"start": start.isoformat(), "end": end.isoformat(), "fill": "open_meteo"}, headers=ident.headers),
        timeout_s=settings.source_timeout_s,
        tenant=ident.tenant_id,
    )
    return mark_empty(res, "days")
