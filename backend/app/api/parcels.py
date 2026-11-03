"""GET {prefix}/parcels - parcel list with one overall light per parcel."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from ..auth import identity
from ..compose import parcels as compose
from ..forward import from_request
from ..schemas import ParcelsV1
from ..sources import crop_health, risk
from ..sources.base import gather_with_budget

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/parcels", response_model=ParcelsV1)
async def get_parcels(request: Request, ctx=identity):
    app = request.app
    settings = app.state.settings
    tenant = ctx.tenant_id
    cached = app.state.cache_parcels.get(tenant, "parcels")
    if cached is not None:
        return cached

    ident = from_request(request, ctx)
    http = app.state.http
    shared = app.state.cache_parcels.get(tenant, "ch:parcels")
    calls = {"risk_alerts": risk.active_alerts(http, settings, ident)}
    if shared is None:
        calls["parcels"] = crop_health.parcels(http, settings, ident)
    res = await gather_with_budget(settings.request_budget_s, **calls)
    if shared is not None:
        res["parcels"] = shared
    elif res["parcels"].status in ("ok", "empty"):
        app.state.cache_parcels.set(tenant, "ch:parcels", res["parcels"])
    out = compose.build(now=datetime.now(timezone.utc), **res)
    logger.info("parcels tenant=%s rows=%d source=%s", tenant, len(out.parcels), out.sources.cropHealth)
    app.state.cache_parcels.set(tenant, "parcels", out)
    return out
