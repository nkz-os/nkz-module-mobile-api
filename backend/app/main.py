"""Mobile API - application factory."""

from contextlib import asynccontextmanager

from nkz_platform_sdk.module_app import ModuleApp

from .api import briefing as briefing_api
from .auth import ensure_signature_enforced
from .cache import TTLCache
from .config import get_settings
from .sources.base import client as http_client


def create_app() -> ModuleApp:
    settings = get_settings()
    ensure_signature_enforced(settings)

    @asynccontextmanager
    async def lifespan(app):
        app.state.http = http_client(settings)
        try:
            yield
        finally:
            await app.state.http.aclose()

    app = ModuleApp(id="mobile-api", description="Mobile app composition API",
                    version=settings.app_version, lifespan=lifespan)
    app.state.settings = settings
    app.state.cache_briefing = TTLCache(settings.cache_ttl_briefing_s)
    app.state.cache_today = TTLCache(settings.cache_ttl_today_s)
    app.state.cache_parcels = TTLCache(settings.cache_ttl_parcels_s)
    app.state.cache_series = TTLCache(settings.cache_ttl_series_s)
    app.include_router(briefing_api.router, prefix=settings.api_prefix)
    return app


app = create_app()
