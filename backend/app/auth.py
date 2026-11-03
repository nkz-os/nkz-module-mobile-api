"""Incoming auth: SDK require_auth plus a fail-fast signature check."""

import logging

from nkz_platform_sdk.auth import require_auth

from .config import Settings

logger = logging.getLogger(__name__)

identity = require_auth()


def ensure_signature_enforced(settings: Settings) -> None:
    """Refuse to start when gateway signatures would not be checked (fail-open otherwise)."""
    if settings.require_hmac_signature and not settings.hmac_secret:
        logger.critical("REQUIRE_HMAC_SIGNATURE is true but HMAC_SECRET is empty")
        raise RuntimeError("HMAC_SECRET is required when REQUIRE_HMAC_SIGNATURE=true")
