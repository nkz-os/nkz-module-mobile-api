"""Mobile API - application factory."""

from contextlib import asynccontextmanager

from nkz_platform_sdk.module_app import ModuleApp

from .auth import ensure_signature_enforced
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
    # Routers are included here under settings.api_prefix (added in later tasks).
    return app


app = create_app()
