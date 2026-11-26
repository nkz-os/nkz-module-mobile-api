"""Mobile API - application factory."""

import logging
from contextlib import asynccontextmanager

from nkz_platform_sdk.module_app import ModuleApp

from .api import briefing as briefing_api
from .api import parcels as parcels_api
from .api import photos as photos_api
from .api import series as series_api
from .api import today as today_api
from .auth import ensure_signature_enforced
from .cache import SWRCache, TTLCache, make_redis_client
from .config import get_settings
from .sources.base import client as http_client

logger = logging.getLogger(__name__)


def create_app() -> ModuleApp:
    settings = get_settings()
    ensure_signature_enforced(settings)
    redis_client = make_redis_client(settings)

    @asynccontextmanager
    async def lifespan(app):
        app.state.http = http_client(settings)
        try:
            yield
        finally:
            for swr in (app.state.swr_briefing, app.state.swr_today, app.state.swr_parcels):
                try:
                    await swr.aclose()
                except Exception:  # noqa: BLE001
                    logger.exception("closing SWR cache failed")
            if redis_client is not None:
                try:
                    await redis_client.aclose()
                except Exception:  # noqa: BLE001
                    logger.exception("closing redis client failed")
            try:
                await app.aclose()  # SDK: closes the cached per-tenant Orion clients
            except Exception:  # noqa: BLE001 - never block the rest of the shutdown
                logger.exception("closing SDK clients failed")
            await app.state.http.aclose()

    app = ModuleApp(id="mobile-api", description="Mobile app composition API",
                    version=settings.app_version, lifespan=lifespan)
    app.state.settings = settings
    app.state.redis = redis_client
    app.state.swr_briefing = SWRCache(
        settings.cache_ttl_briefing_s,
        settings.cache_stale_ttl_briefing_s,
        redis_client=redis_client,
        key_prefix=settings.redis_key_prefix,
    )
    app.state.swr_today = SWRCache(
        settings.cache_ttl_today_s,
        settings.cache_stale_ttl_today_s,
        redis_client=redis_client,
        key_prefix=settings.redis_key_prefix,
    )
    app.state.swr_parcels = SWRCache(
        settings.cache_ttl_parcels_s,
        settings.cache_stale_ttl_parcels_s,
        redis_client=redis_client,
        key_prefix=settings.redis_key_prefix,
    )
    app.state.cache_parcels = TTLCache(settings.cache_ttl_parcels_s)
    app.state.cache_series = TTLCache(settings.cache_ttl_series_s)
    app.include_router(briefing_api.router, prefix=settings.api_prefix)
    app.include_router(today_api.router, prefix=settings.api_prefix)
    app.include_router(parcels_api.router, prefix=settings.api_prefix)
    app.include_router(photos_api.router, prefix=settings.api_prefix)
    app.include_router(series_api.router, prefix=settings.api_prefix)
    return app


app = create_app()
