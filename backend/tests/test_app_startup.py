import pytest

from app.config import get_settings


def test_refuses_to_start_without_hmac_secret(settings_env, monkeypatch):
    # settings_env lets the module-level `app = create_app()` import succeed first.
    from app.main import create_app

    monkeypatch.setenv("REQUIRE_HMAC_SIGNATURE", "true")
    monkeypatch.setenv("HMAC_SECRET", "")
    get_settings.cache_clear()

    try:
        with pytest.raises(RuntimeError):
            create_app()
    finally:
        get_settings.cache_clear()


def test_health_ready(client):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
