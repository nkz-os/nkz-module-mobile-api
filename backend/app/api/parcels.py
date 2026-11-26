"""GET {prefix}/parcels - parcel list with one overall light per parcel."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from ..auth import identity
from ..compose import parcels as compose
from ..config import Settings
from ..forward import Identity, from_request
from ..schemas import ParcelsV1
from ..sources import crop_health, risk
from ..sources.base import gather_with_budget

logger = logging.getLogger(__name__)
router = APIRouter()


def _refresh_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "source_timeout_s": settings.swr_refresh_source_timeout_s,
            "source_timeout_parcels_s": settings.swr_refresh_timeout_parcels_s,
            "request_budget_s": settings.swr_refresh_budget_s,
        }
    )


async def _fetch_parcels(
    app,
    settings: Settings,
    ident: Identity,
    *,
    allow_shared: bool = True,
) -> tuple[ParcelsV1, bool]:
    http = app.state.http
    tenant = ident.tenant_id
    shared = app.state.cache_parcels.get(tenant, "ch:parcels") if allow_shared else None
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
    good = res["parcels"].status in ("ok", "empty") and res["risk_alerts"].status in ("ok", "empty")
    return out, good


@router.get("/parcels", response_model=ParcelsV1)
async def get_parcels(request: Request, ctx=identity):
    app = request.app
    settings = app.state.settings
    tenant = ctx.tenant_id
    key = "parcels"

    hit = await app.state.swr_parcels.get(tenant, key)
    if hit.status == "fresh" and hit.payload is not None:
        return ParcelsV1.model_validate(hit.payload)

    ident = from_request(request, ctx)
    fetch_cfg = _refresh_settings(settings)
    if hit.status == "stale" and hit.payload is not None:

        async def _refresh() -> None:
            out, good = await _fetch_parcels(app, fetch_cfg, ident, allow_shared=False)
            if good:
                await app.state.swr_parcels.set(tenant, key, out.model_dump(by_alias=True))

        app.state.swr_parcels.trigger_refresh(tenant, key, _refresh)
        return ParcelsV1.model_validate(hit.payload).model_copy(update={"stale": True})

    out, good = await _fetch_parcels(app, fetch_cfg, ident, allow_shared=True)
    if good:
        await app.state.swr_parcels.set(tenant, key, out.model_dump(by_alias=True))
    return out
