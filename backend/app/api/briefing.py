"""GET {prefix}/briefing/{parcel_id} - one-call parcel summary."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..auth import identity
from ..compose import briefing as compose
from ..config import Settings
from ..forward import Identity, from_request
from ..ids import is_valid, to_short, to_urn
from ..schemas import BriefingV1
from ..sources import crop_health, field_ops, orion, risk, soil, weather
from ..sources.base import gather_with_budget
from .errors import bad_request

logger = logging.getLogger(__name__)
router = APIRouter()
LANGS = ("es", "eu", "en")


def _refresh_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "source_timeout_parcels_s": settings.swr_refresh_timeout_parcels_s,
            "request_budget_s": settings.swr_refresh_budget_s,
        }
    )


async def _fetch_briefing(
    app,
    settings: Settings,
    ident: Identity,
    client,
    urn: str,
    lang: str,
) -> tuple[BriefingV1 | None, bool, bool]:
    tenant = ident.tenant_id
    http = app.state.http
    exists = await orion.parcel_exists(client, urn, ident.request_id)
    if exists.status == "empty":
        return None, False, True
    name = None
    if exists.status == "ok" and isinstance(exists.data, dict):
        n = exists.data.get("name")
        name = n if isinstance(n, str) and n else None

    short = to_short(urn)
    res = await gather_with_budget(
        settings.request_budget_s,
        crop=orion.crop(tenant, urn, client, ident.request_id),
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
    out = compose.build(
        parcel_urn=urn,
        parcel_name=name,
        lang=lang,
        now=datetime.now(timezone.utc),
        **res,
    )
    logger.info("briefing tenant=%s urn=%s sources=%s", tenant, urn, out.sources.model_dump())
    # A degraded response must not be frozen for the TTL.
    good = exists.status == "ok" and not any(
        v in ("failed", "timeout") for v in out.sources.model_dump().values()
    )
    return out, good, False


@router.get("/briefing/{parcel_id:path}", response_model=BriefingV1)
async def get_briefing(
    request: Request,
    parcel_id: str,
    lang: str | None = Query(default=None),
    ctx=identity,
):
    app = request.app
    settings = app.state.settings
    lang = lang or settings.default_lang
    if lang not in LANGS:
        return bad_request("invalid_lang")
    if not is_valid(parcel_id):
        return bad_request("invalid_parcel_id")
    urn = to_urn(parcel_id)
    tenant = ctx.tenant_id
    key = f"briefing:{urn}:{lang}"

    hit = await app.state.swr_briefing.get(tenant, key)
    if hit.status == "fresh" and hit.payload is not None:
        return BriefingV1.model_validate(hit.payload)

    ident = from_request(request, ctx)
    client = app.orion(ctx)
    if hit.status == "stale" and hit.payload is not None:
        refresh_cfg = _refresh_settings(settings)

        async def _refresh() -> None:
            out, good, _not_found = await _fetch_briefing(app, refresh_cfg, ident, client, urn, lang)
            if good and out is not None:
                await app.state.swr_briefing.set(tenant, key, out.model_dump(by_alias=True))

        app.state.swr_briefing.trigger_refresh(tenant, key, _refresh)
        return BriefingV1.model_validate(hit.payload).model_copy(update={"stale": True})

    out, good, not_found = await _fetch_briefing(app, settings, ident, client, urn, lang)
    if not_found or out is None:
        return JSONResponse(status_code=404, content={"error": "parcel_not_found"})
    if good:
        await app.state.swr_briefing.set(tenant, key, out.model_dump(by_alias=True))
    return out
