"""GET {prefix}/today - prioritized "Hoy" feed across all parcels."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request

from ..auth import identity
from ..compose import today as compose
from ..config import Settings
from ..forward import Identity, from_request
from ..schemas import TodayV1
from ..sources import crop_health, notifications, risk, weather
from ..sources.base import gather_with_budget
from .errors import bad_request

logger = logging.getLogger(__name__)
router = APIRouter()
LANGS = ("es", "eu", "en")
REPORT_ROLES = ("TenantAdmin", "TechnicalConsultant")


def _refresh_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "source_timeout_parcels_s": settings.swr_refresh_timeout_parcels_s,
            "request_budget_s": settings.swr_refresh_budget_s,
        }
    )


async def _fetch_today(
    app,
    settings: Settings,
    ident: Identity,
    lang: str,
    wants_report: bool,
) -> tuple[TodayV1, bool]:
    http = app.state.http
    tenant = ident.tenant_id
    sources = {}
    if wants_report:
        sources["report"] = notifications.weekly_report(http, settings, ident, lang)
    res = await gather_with_budget(
        settings.request_budget_s,
        **sources,
        parcels=crop_health.parcels(http, settings, ident),
        risk_alerts=risk.active_alerts(http, settings, ident),
        wx_alerts=weather.tenant_alerts(http, settings, ident),
    )
    # Reused by the parcels list endpoint: keep ok/empty, never failed/timeout.
    if res["parcels"].status in ("ok", "empty"):
        app.state.cache_parcels.set(tenant, "ch:parcels", res["parcels"])
    out = compose.build(now=datetime.now(timezone.utc), lang=lang, **res)
    logger.info("today tenant=%s cards=%d sources=%s", tenant, len(out.cards), out.sources.model_dump())
    good = not any(v in ("failed", "timeout") for v in out.sources.model_dump().values())
    return out, good


@router.get("/today", response_model=TodayV1)
async def get_today(request: Request, lang: str | None = Query(default=None), ctx=identity):
    app = request.app
    settings = app.state.settings
    lang = lang or settings.default_lang
    if lang not in LANGS:
        return bad_request("invalid_lang")
    tenant = ctx.tenant_id
    wants_report = ctx.has_any_role(REPORT_ROLES)
    key = f"today:{lang}:{'report' if wants_report else 'noreport'}"

    hit = await app.state.swr_today.get(tenant, key)
    if hit.status == "fresh" and hit.payload is not None:
        return TodayV1.model_validate(hit.payload)

    ident = from_request(request, ctx)
    if hit.status == "stale" and hit.payload is not None:
        refresh_cfg = _refresh_settings(settings)

        async def _refresh() -> None:
            out, good = await _fetch_today(app, refresh_cfg, ident, lang, wants_report)
            if good:
                await app.state.swr_today.set(tenant, key, out.model_dump(by_alias=True))

        app.state.swr_today.trigger_refresh(tenant, key, _refresh)
        return TodayV1.model_validate(hit.payload).model_copy(update={"stale": True})

    out, good = await _fetch_today(app, settings, ident, lang, wants_report)
    if good:
        await app.state.swr_today.set(tenant, key, out.model_dump(by_alias=True))
    return out
