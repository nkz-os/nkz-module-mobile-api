"""Shared fixtures. Client style for all tasks: fastapi.testclient.TestClient (sync)."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def settings_env(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("REQUIRE_HMAC_SIGNATURE", "false")
    monkeypatch.setenv("HMAC_SECRET", "")
    monkeypatch.setenv("CROP_HEALTH_URL", "http://ch")
    monkeypatch.setenv("WEATHER_API_URL", "http://wx")
    monkeypatch.setenv("SOIL_URL", "http://soil")
    monkeypatch.setenv("FIELD_OPS_URL", "http://fo")
    monkeypatch.setenv("RISK_URL", "http://risk")
    monkeypatch.setenv("VEGETATION_URL", "http://veg")
    monkeypatch.setenv("ORION_LD_URL", "http://orion:1026")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(settings_env):
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def auth_headers():
    return {
        "X-Tenant-ID": "acmefarm",
        "X-User-ID": "user-1",
        "X-User-Roles": "Farmer",
        "Authorization": "Bearer t",
        "X-Auth-Signature": "sig:1",
    }
