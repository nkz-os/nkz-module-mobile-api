"""Mobile API - configuration (environment based)."""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    app_version: str = "0.1.0"
    api_prefix: str = "/api/mobile"

    # Source services (in-cluster defaults, overridable by env)
    crop_health_url: str = "http://crop-health-api-service:8000"
    weather_api_url: str = "http://weather-api-service:8000"
    soil_url: str = "http://soil-module-service:8000"
    field_ops_url: str = "http://field-operations-api-service:8420"
    risk_url: str = "http://risk-module-api-service:8000"
    vegetation_url: str = "http://vegetation-prime-api-service:8000"
    notifications_url: str = "http://notifications-api-service:8000"

    # Deadlines (seconds)
    source_timeout_s: float = 5.0
    source_timeout_parcels_s: float = 10.0  # crop-health /parcels fans out per parcel
    request_budget_s: float = 12.0

    # Cache TTLs (seconds)
    cache_ttl_briefing_s: int = 60
    cache_ttl_today_s: int = 30
    cache_ttl_parcels_s: int = 60
    cache_ttl_series_s: int = 300

    default_lang: str = "es"

    require_hmac_signature: bool = Field(
        True, validation_alias=AliasChoices("REQUIRE_HMAC_SIGNATURE", "require_hmac_signature")
    )
    hmac_secret: str = Field(
        "", validation_alias=AliasChoices("HMAC_SECRET", "hmac_secret")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
