"""GET {prefix}/briefing/{parcel_id} - one-call parcel summary."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..auth import identity
from .errors import bad_request
from ..compose import briefing as compose
from ..forward import from_request
from ..ids import to_short, to_urn
from ..schemas import BriefingV1
from ..sources import crop_health, field_ops, orion, risk, soil, weather
from ..sources.base import gather_with_budget

logger = logging.getLogger(__name__)
router = APIRouter()
LANGS = ("es", "eu", "en")


@router.get("/briefing/{parcel_id:path}", response_model=BriefingV1)
async def get_briefing(request: Request, parcel_id: str, lang: str | None = Query(default=None),
                       ctx=identity):
    app = request.app
    settings = app.state.settings
    lang = lang or settings.default_lang
    if lang not in LANGS:
        return bad_request("invalid_lang")
    urn = to_urn(parcel_id)
    tenant = ctx.tenant_id
    key = f"briefing:{urn}:{lang}"
    cached = app.state.cache_briefing.get(tenant, key)
    if cached is not None:
        return cached

    ident = from_request(request, ctx)
    http = app.state.http
    client = app.orion(ctx)

    exists = await orion.parcel_exists(client, urn)
    if exists.status == "empty":
        return JSONResponse(status_code=404, content={"error": "parcel_not_found"})
    name = None
    if exists.status == "ok" and isinstance(exists.data, dict):
        n = exists.data.get("name")
        name = n if isinstance(n, str) and n else None

    short = to_short(urn)
    res = await gather_with_budget(
        settings.request_budget_s,
        crop=orion.crop(tenant, urn, client),
        latest=crop_health.latest(http, settings, ident, short),
        diseases=crop_health.diseases_active(http, settings, ident, short),
        phenology=crop_health.phenology(http, settings, ident, urn),
        agro=weather.agro_status(http, settings, ident, urn),
        forecast3=weather.forecast(http, settings, ident, urn, days=3),
        wx_alerts=weather.parcel_alerts(http, settings, ident, urn),
        soil_summary=soil.summary(http, settings, ident, urn),
        labs=soil.lab_analyses(http, settings, ident, urn),
        ops=field_ops.operations(http, settings, ident, urn),
        risk_alerts=risk.active_alerts(http, settings, ident),
        yield_fc=crop_health.yield_forecast(http, settings, ident, urn),
    )
    out = compose.build(parcel_urn=urn, parcel_name=name, lang=lang,
                        now=datetime.now(timezone.utc), **res)
    logger.info("briefing tenant=%s urn=%s sources=%s", tenant, urn, out.sources.model_dump())
    app.state.cache_briefing.set(tenant, key, out)
    return out
