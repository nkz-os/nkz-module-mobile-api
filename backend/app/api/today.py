"""GET {prefix}/today - prioritized "Hoy" feed across all parcels."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from ..auth import identity
from ..compose import today as compose
from ..forward import from_request
from ..schemas import TodayV1
from ..sources import crop_health, risk, weather
from ..sources.base import gather_with_budget

logger = logging.getLogger(__name__)
router = APIRouter()
LANGS = ("es", "eu", "en")


@router.get("/today", response_model=TodayV1)
async def get_today(request: Request, lang: str | None = Query(default=None), ctx=identity):
    app = request.app
    settings = app.state.settings
    lang = lang or settings.default_lang
    if lang not in LANGS:
        raise HTTPException(status_code=400, detail="invalid_lang")
    tenant = ctx.tenant_id
    key = f"today:{lang}"
    cached = app.state.cache_today.get(tenant, key)
    if cached is not None:
        return cached

    ident = from_request(request, ctx)
    http = app.state.http
    res = await gather_with_budget(
        settings.request_budget_s,
        parcels=crop_health.parcels(http, settings, ident),
        risk_alerts=risk.active_alerts(http, settings, ident),
        wx_alerts=weather.tenant_alerts(http, settings, ident),
    )
    # Reused by the parcels list endpoint: keep ok/empty, never failed/timeout.
    if res["parcels"].status in ("ok", "empty"):
        app.state.cache_parcels.set(tenant, "ch:parcels", res["parcels"])
    out = compose.build(now=datetime.now(timezone.utc), lang=lang, **res)
    logger.info("today tenant=%s cards=%d sources=%s", tenant, len(out.cards), out.sources.model_dump())
    app.state.cache_today.set(tenant, key, out)
    return out
