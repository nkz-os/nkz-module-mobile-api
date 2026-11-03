"""GET {prefix}/parcels/{parcel_id}/series - one metric over 7/30/90 days."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request

from ..auth import identity
from .errors import bad_request
from ..compose import series as compose
from ..forward import from_request
from ..ids import to_short, to_urn
from ..schemas import SeriesV1
from ..sources import crop_health, vegetation, weather
from ..sources.base import gather_with_budget

logger = logging.getLogger(__name__)
router = APIRouter()
METRICS = ("water_balance", "cwsi", "rain", "tmax", "tmin", "vigor")
DAYS = (7, 30, 90)


@router.get("/parcels/{parcel_id:path}/series", response_model=SeriesV1)
async def get_series(request: Request, parcel_id: str, metric: str | None = Query(default=None),
                     days: str | None = Query(default=None), ctx=identity):
    if metric not in METRICS:
        return bad_request("invalid_metric")
    try:
        n = int(days) if days is not None else 0
    except ValueError:
        n = 0
    if n not in DAYS:
        return bad_request("invalid_days")
    app = request.app
    settings = app.state.settings
    urn = to_urn(parcel_id)
    tenant = ctx.tenant_id
    key = f"series:{urn}:{metric}:{n}"
    cached = app.state.cache_series.get(tenant, key)
    if cached is not None:
        return cached

    ident = from_request(request, ctx)
    http = app.state.http
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=n)
    if metric in ("water_balance", "cwsi"):
        src = crop_health.history(http, settings, ident, to_short(urn), n)
    elif metric == "vigor":
        src = vegetation.ndvi_history(http, settings, ident, urn, start, end)
    else:
        src = weather.daily(http, settings, ident, urn, start, end)
    raw = (await gather_with_budget(settings.request_budget_s, raw=src))["raw"]
    out = compose.build(metric, n, raw)
    logger.info("series tenant=%s urn=%s metric=%s days=%d source=%s", tenant, urn, metric, n, out.source)
    if out.source in ("ok", "empty"):
        app.state.cache_series.set(tenant, key, out)
    return out
