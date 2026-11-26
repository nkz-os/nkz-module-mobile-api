"""Tests for stale-while-revalidate (SWR) caching and singleflight refresh on /today, /parcels, /briefing."""

import asyncio

import httpx
import pytest

from app.cache import SWRCache
from app.sources import orion
from tests.helpers import load_fixture

URN = "urn:ngsi-ld:AgriParcel:p1"
ENT = "http://orion:1026/ngsi-ld/v1/entities"

PARCELS_V1 = {
    "parcels": [
        {
            "parcelId": "p1",
            "parcelName": "Norte",
            "hasData": True,
            "cropStatus": "active",
            "overallSeverity": "LOW",
            "cropName": "Wheat",
            "phenologyStage": "tillering",
            "freshness": "fresh",
            "nextJob": {"kind": "irrigate", "when": "today", "detail": {"mm": 10}},
        }
    ]
}
PARCELS_V2 = {
    "parcels": [
        {
            "parcelId": "p1",
            "parcelName": "Norte Updated",
            "hasData": True,
            "cropStatus": "active",
            "overallSeverity": "MEDIUM",
            "cropName": "Barley",
            "phenologyStage": "heading",
            "freshness": "fresh",
            "nextJob": {"kind": "scout", "when": "today", "detail": {}},
        }
    ]
}
RISK_EMPTY = {"alerts": []}
WX_EMPTY = {"alerts": []}
TIMELINE = {"current": {"species": "TRZAX", "start": {"date": "2026-10-20", "provenance": "actual"}}}


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.down = False

    async def get(self, key: str) -> str | None:
        if self.down:
            raise ConnectionError("redis unavailable")
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self.down:
            raise ConnectionError("redis unavailable")
        self.store[key] = value


@pytest.fixture
def clock():
    return [10_000.0]


@pytest.fixture
def async_client(settings_env, clock):
    """Async httpx client bound to the ASGI app so background asyncio tasks share the test event loop."""
    from app.main import create_app

    app = create_app()
    s = app.state.settings
    app.state.swr_today = SWRCache(s.cache_ttl_today_s, s.cache_stale_ttl_today_s, clock=lambda: clock[0])
    app.state.swr_parcels = SWRCache(s.cache_ttl_parcels_s, s.cache_stale_ttl_parcels_s, clock=lambda: clock[0])
    app.state.swr_briefing = SWRCache(s.cache_ttl_briefing_s, s.cache_stale_ttl_briefing_s, clock=lambda: clock[0])
    return app


@pytest.mark.asyncio
async def test_today_swr_fresh_stale_singleflight_and_extended_budget(async_client, auth_headers, respx_mock, clock, monkeypatch):
    app = async_client
    observed_budgets: list[tuple[float, float, float]] = []
    gate = asyncio.Event()
    refresh_calls = 0

    from app.sources import crop_health as ch_mod

    orig_parcels = ch_mod.parcels

    async def spy_parcels(http, settings, ident):
        nonlocal refresh_calls
        observed_budgets.append(
            (settings.source_timeout_s, settings.source_timeout_parcels_s, settings.request_budget_s)
        )
        if len(observed_budgets) > 1:
            refresh_calls += 1
            await gate.wait()
        return await orig_parcels(http, settings, ident)

    monkeypatch.setattr(ch_mod, "parcels", spy_parcels)

    parcels_route = respx_mock.get("http://ch/api/crop-health/parcels").mock(
        return_value=httpx.Response(200, json=PARCELS_V1)
    )
    respx_mock.get("http://risk/api/risk/alerts").mock(return_value=httpx.Response(200, json=RISK_EMPTY))
    respx_mock.get("http://wx/api/weather/alerts").mock(return_value=httpx.Response(200, json=WX_EMPTY))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. Cold miss -> foreground fetch uses extended budget so first request populates cache
            r1 = await ac.get("/api/mobile/today", headers=auth_headers)
            assert r1.status_code == 200
            b1 = r1.json()
            assert "stale" not in b1
            assert b1["generatedAt"]
            assert observed_budgets == [(12.0, 20.0, 25.0)]

            # 2. Fresh hit -> no upstream call, no stale flag, identical generatedAt
            clock[0] += 10.0
            r2 = await ac.get("/api/mobile/today", headers=auth_headers)
            assert r2.status_code == 200
            b2 = r2.json()
            assert "stale" not in b2
            assert b2["generatedAt"] == b1["generatedAt"]
            assert parcels_route.call_count == 1

            # 3. Past fresh TTL (30s) -> stale hit immediately + singleflight background refresh
            parcels_route.mock(return_value=httpx.Response(200, json=PARCELS_V2))
            clock[0] += 25.0  # total +35s > 30s fresh TTL
            r3 = await ac.get("/api/mobile/today", headers=auth_headers)
            r4 = await ac.get("/api/mobile/today", headers=auth_headers)
            b3, b4 = r3.json(), r4.json()
            assert b3["stale"] is True and b3["generatedAt"] == b1["generatedAt"]
            assert b4["stale"] is True and b4["generatedAt"] == b1["generatedAt"]
            assert b3["cards"][0]["parcelName"] == "Norte"

            # Release background refresh gate and wait for singleflight completion
            await asyncio.sleep(0)
            assert refresh_calls == 1  # singleflight: only 1 in-flight refresh despite 2 stale requests
            gate.set()
            await app.state.swr_today.wait_inflight()

            # Extended budget was used for both cold miss and background refresh
            assert observed_budgets == [(12.0, 20.0, 25.0), (12.0, 20.0, 25.0)]

            # 4. Next request gets the refreshed fresh payload without stale flag
            r5 = await ac.get("/api/mobile/today", headers=auth_headers)
            b5 = r5.json()
            assert "stale" not in b5
            assert b5["cards"][0]["parcelName"] == "Norte Updated"


@pytest.mark.asyncio
async def test_today_degraded_refresh_does_not_overwrite_good_cache(async_client, auth_headers, respx_mock, clock):
    app = async_client
    parcels_route = respx_mock.get("http://ch/api/crop-health/parcels").mock(
        return_value=httpx.Response(200, json=PARCELS_V1)
    )
    risk_route = respx_mock.get("http://risk/api/risk/alerts").mock(
        return_value=httpx.Response(200, json=RISK_EMPTY)
    )
    respx_mock.get("http://wx/api/weather/alerts").mock(return_value=httpx.Response(200, json=WX_EMPTY))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            r1 = await ac.get("/api/mobile/today", headers=auth_headers)
            good_gen = r1.json()["generatedAt"]

            # Make upstream fail during background refresh
            risk_route.mock(return_value=httpx.Response(500))
            clock[0] += 35.0
            r2 = await ac.get("/api/mobile/today", headers=auth_headers)
            assert r2.json()["stale"] is True
            await app.state.swr_today.wait_inflight()

            # Good cached entry must still be preserved (not overwritten by degraded response)
            r3 = await ac.get("/api/mobile/today", headers=auth_headers)
            b3 = r3.json()
            assert b3["stale"] is True
            assert b3["generatedAt"] == good_gen
            assert b3["sources"]["risk"] == "empty"
            await app.state.swr_today.wait_inflight()
            assert parcels_route.call_count == 3


@pytest.mark.asyncio
async def test_parcels_swr_stale_refresh_bypasses_shared_and_preserves_good_on_degraded(
    async_client, auth_headers, respx_mock, clock, monkeypatch
):
    app = async_client
    observed_budgets: list[tuple[float, float, float]] = []

    from app.sources import crop_health as ch_mod

    orig_parcels = ch_mod.parcels

    async def spy_parcels(http, settings, ident):
        observed_budgets.append(
            (settings.source_timeout_s, settings.source_timeout_parcels_s, settings.request_budget_s)
        )
        return await orig_parcels(http, settings, ident)

    monkeypatch.setattr(ch_mod, "parcels", spy_parcels)

    parcels_route = respx_mock.get("http://ch/api/crop-health/parcels").mock(
        return_value=httpx.Response(200, json=PARCELS_V1)
    )
    risk_route = respx_mock.get("http://risk/api/risk/alerts").mock(
        return_value=httpx.Response(200, json=RISK_EMPTY)
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            r1 = await ac.get("/api/mobile/parcels", headers=auth_headers)
            b1 = r1.json()
            assert "stale" not in b1
            assert b1["parcels"][0]["parcelName"] == "Norte"
            assert observed_budgets == [(12.0, 20.0, 25.0)]

            # Fresh hit
            clock[0] += 20.0
            r2 = await ac.get("/api/mobile/parcels", headers=auth_headers)
            assert "stale" not in r2.json()
            assert parcels_route.call_count == 1

            # Degraded background refresh must not overwrite good cache
            parcels_route.mock(return_value=httpx.Response(500))
            clock[0] += 45.0  # total +65s > 60s fresh TTL
            r3 = await ac.get("/api/mobile/parcels", headers=auth_headers)
            assert r3.json()["stale"] is True
            assert r3.json()["parcels"][0]["parcelName"] == "Norte"
            await app.state.swr_parcels.wait_inflight()

            # Now upstream recovers -> next stale request triggers refresh and updates cache
            parcels_route.mock(return_value=httpx.Response(200, json=PARCELS_V2))
            r4 = await ac.get("/api/mobile/parcels", headers=auth_headers)
            assert r4.json()["stale"] is True
            await app.state.swr_parcels.wait_inflight()

            r5 = await ac.get("/api/mobile/parcels", headers=auth_headers)
            b5 = r5.json()
            assert "stale" not in b5
            assert b5["parcels"][0]["parcelName"] == "Norte Updated"
            assert risk_route.call_count == 3
            assert observed_budgets == [(12.0, 20.0, 25.0)] * 3


@pytest.mark.asyncio
async def test_briefing_swr_fresh_stale_and_degraded_protection(
    async_client, auth_headers, respx_mock, clock, monkeypatch
):
    app = async_client
    observed_budgets: list[tuple[float, float, float]] = []

    from app.sources import weather as wx_mod

    orig_agro = wx_mod.agro_status

    async def spy_agro(http, settings, ident, urn):
        observed_budgets.append(
            (settings.source_timeout_s, settings.source_timeout_parcels_s, settings.request_budget_s)
        )
        return await orig_agro(http, settings, ident, urn)

    monkeypatch.setattr(wx_mod, "agro_status", spy_agro)

    async def fake_timeline(tenant, urn, *a, **k):
        return TIMELINE

    monkeypatch.setattr(orion, "fetch_crop_timeline", fake_timeline)

    orion_route = respx_mock.get(f"{ENT}/{URN}").mock(
        return_value=httpx.Response(200, json={"id": URN, "name": "Norte"})
    )
    respx_mock.get("http://ch/api/crop-health/assessments/latest").mock(
        return_value=httpx.Response(200, json=load_fixture("crop_health/latest"))
    )
    respx_mock.get("http://ch/api/crop-health/diseases/active").mock(
        return_value=httpx.Response(200, json=load_fixture("crop_health/diseases_active"))
    )
    respx_mock.get(f"http://ch/api/crop-health/parcels/{URN}/phenology-status").mock(
        return_value=httpx.Response(200, json=load_fixture("crop_health/phenology"))
    )
    respx_mock.get(f"http://ch/api/crop-health/parcels/{URN}/yield-forecast").mock(
        return_value=httpx.Response(200, json=load_fixture("crop_health/yield_forecast"))
    )
    respx_mock.get(f"http://wx/api/weather/parcel/{URN}/agro-status").mock(
        return_value=httpx.Response(200, json=load_fixture("weather/agro_status"))
    )
    respx_mock.get(f"http://wx/api/weather/parcel/{URN}/forecast").mock(
        return_value=httpx.Response(200, json=load_fixture("weather/forecast"))
    )
    respx_mock.get(f"http://wx/api/weather/parcel/{URN}/alerts").mock(
        return_value=httpx.Response(200, json=load_fixture("weather/parcel_alerts"))
    )
    respx_mock.get(f"http://soil/v1/soil/parcel/{URN}/summary").mock(
        return_value=httpx.Response(200, json=load_fixture("soil/summary"))
    )
    respx_mock.get(f"http://soil/v1/soil/parcel/{URN}/lab-analyses").mock(
        return_value=httpx.Response(200, json=load_fixture("soil/lab_analyses"))
    )
    ops_route = respx_mock.get("http://fo/api/field-operations/operations").mock(
        return_value=httpx.Response(200, json=load_fixture("field_ops/operations"))
    )
    respx_mock.get("http://risk/api/risk/alerts").mock(
        return_value=httpx.Response(200, json=load_fixture("risk/active_alerts"))
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            r1 = await ac.get("/api/mobile/briefing/p1", headers=auth_headers)
            b1 = r1.json()
            assert r1.status_code == 200 and "stale" not in b1
            assert b1["parcelName"] == "Norte"
            assert observed_budgets == [(12.0, 20.0, 25.0)]

            # Fresh hit
            clock[0] += 30.0
            r2 = await ac.get("/api/mobile/briefing/p1", headers=auth_headers)
            assert "stale" not in r2.json()
            assert orion_route.call_count == 1

            # Degraded refresh (ops 500) must not overwrite good cache
            ops_route.mock(return_value=httpx.Response(500))
            clock[0] += 35.0  # total +65s > 60s
            r3 = await ac.get("/api/mobile/briefing/p1", headers=auth_headers)
            assert r3.json()["stale"] is True and r3.json()["parcelName"] == "Norte"
            await app.state.swr_briefing.wait_inflight()

            # Recovery refresh updates cached name
            ops_route.mock(return_value=httpx.Response(200, json=load_fixture("field_ops/operations")))
            orion_route.mock(return_value=httpx.Response(200, json={"id": URN, "name": "Norte v2"}))
            r4 = await ac.get("/api/mobile/briefing/p1", headers=auth_headers)
            assert r4.json()["stale"] is True and r4.json()["parcelName"] == "Norte"
            await app.state.swr_briefing.wait_inflight()

            r5 = await ac.get("/api/mobile/briefing/p1", headers=auth_headers)
            assert "stale" not in r5.json() and r5.json()["parcelName"] == "Norte v2"
            assert observed_budgets == [(12.0, 20.0, 25.0)] * 3


@pytest.mark.asyncio
async def test_parcels_swr_redis_outage_falls_back_to_memory(settings_env, auth_headers, respx_mock):
    from app.main import create_app

    t = [5000.0]
    redis = FakeRedis()
    app = create_app()
    app.state.swr_parcels = SWRCache(60, 600, redis_client=redis, clock=lambda: t[0])

    parcels_route = respx_mock.get("http://ch/api/crop-health/parcels").mock(
        return_value=httpx.Response(200, json=PARCELS_V1)
    )
    respx_mock.get("http://risk/api/risk/alerts").mock(return_value=httpx.Response(200, json=RISK_EMPTY))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            r1 = await ac.get("/api/mobile/parcels", headers=auth_headers)
            assert r1.status_code == 200 and len(redis.store) == 1

            # Redis goes down: endpoint still serves fresh from in-memory fallback (fail-open)
            redis.down = True
            t[0] += 10.0
            r2 = await ac.get("/api/mobile/parcels", headers=auth_headers)
            assert r2.status_code == 200 and "stale" not in r2.json()
            assert parcels_route.call_count == 1
