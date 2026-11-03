"""Mobile API - application factory."""

from nkz_platform_sdk.module_app import ModuleApp

from .auth import ensure_signature_enforced
from .config import get_settings


def create_app() -> ModuleApp:
    settings = get_settings()
    ensure_signature_enforced(settings)
    app = ModuleApp(id="mobile-api", description="Mobile app composition API",
                    version=settings.app_version)
    # Routers are included here under settings.api_prefix (added in later tasks).
    return app


app = create_app()
