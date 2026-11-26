from app.config import Settings


def test_defaults_point_to_cluster_services(monkeypatch):
    for k in ("CROP_HEALTH_URL", "WEATHER_API_URL", "SOIL_URL", "FIELD_OPS_URL",
              "RISK_URL", "VEGETATION_URL", "API_PREFIX"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.api_prefix == "/api/mobile"
    assert s.crop_health_url == "http://crop-health-api-service:8000"
    assert s.weather_api_url == "http://weather-api-service:8000"
    assert s.soil_url == "http://soil-module-service:8000"
    assert s.field_ops_url == "http://field-operations-api-service:8420"
    assert s.risk_url == "http://risk-module-api-service:8000"
    assert s.vegetation_url == "http://vegetation-prime-api-service:8000"
    assert s.source_timeout_s == 5.0
    assert s.request_budget_s == 12.0


def test_parcels_source_timeout_setting(monkeypatch):
    monkeypatch.delenv("SOURCE_TIMEOUT_PARCELS_S", raising=False)
    assert Settings(_env_file=None).source_timeout_parcels_s == 10.0
    monkeypatch.setenv("SOURCE_TIMEOUT_PARCELS_S", "7")
    assert Settings(_env_file=None).source_timeout_parcels_s == 7.0


def test_swr_and_redis_settings(monkeypatch):
    for k in ("REDIS_URL", "SWR_REFRESH_SOURCE_TIMEOUT_S", "SWR_REFRESH_TIMEOUT_PARCELS_S",
              "SWR_REFRESH_BUDGET_S", "CACHE_STALE_TTL_TODAY_S", "CACHE_STALE_TTL_PARCELS_S",
              "CACHE_STALE_TTL_BRIEFING_S"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.redis_url == ""
    assert s.swr_refresh_source_timeout_s == 12.0
    assert s.swr_refresh_timeout_parcels_s == 20.0
    assert s.swr_refresh_budget_s == 25.0
    assert s.cache_stale_ttl_today_s == 21600
    assert s.cache_stale_ttl_parcels_s == 21600
    assert s.cache_stale_ttl_briefing_s == 21600
