from datetime import date

import httpx
import pytest
import respx

from app.config import get_settings
from app.forward import Identity
from app.sources import crop_health, field_ops, risk, soil, vegetation, weather
from tests.helpers import load_fixture

URN = "urn:ngsi-ld:AgriParcel:p1"
D1, D2 = date(2026, 11, 1), date(2026, 11, 2)


@pytest.fixture
def settings(settings_env):
    return get_settings()


@pytest.fixture
def ident(auth_headers):
    return Identity(headers=auth_headers, tenant_id="acmefarm")


# (module, fn, args, base, path, params, fixture, empty_body)
CASES = [
    (crop_health, "latest", ("p1",), "http://ch", "/api/crop-health/assessments/latest", {"parcelId": "p1"}, "crop_health/latest", {"assessments": []}),
    (crop_health, "parcels", (), "http://ch", "/api/crop-health/parcels", {}, "crop_health/parcels", {"parcels": []}),
    (crop_health, "diseases_active", ("p1",), "http://ch", "/api/crop-health/diseases/active", {"parcelId": "p1"}, "crop_health/diseases_active", {"risks": []}),
    (crop_health, "phenology", (URN,), "http://ch", f"/api/crop-health/parcels/{URN}/phenology-status", {}, "crop_health/phenology", None),
    (crop_health, "history", ("p1", 30), "http://ch", "/api/crop-health/assessments/history", {"parcelId": "p1", "days": "30"}, "crop_health/history", {"points": []}),
    (crop_health, "yield_forecast", (URN,), "http://ch", f"/api/crop-health/parcels/{URN}/yield-forecast", {}, "crop_health/yield_forecast", None),
    (weather, "agro_status", (URN,), "http://wx", f"/api/weather/parcel/{URN}/agro-status", {}, "weather/agro_status", None),
    (weather, "forecast", (URN,), "http://wx", f"/api/weather/parcel/{URN}/forecast", {"days": "3"}, "weather/forecast", {"forecast": []}),
    (weather, "parcel_alerts", (URN,), "http://wx", f"/api/weather/parcel/{URN}/alerts", {}, "weather/parcel_alerts", {"alerts": []}),
    (weather, "tenant_alerts", (), "http://wx", "/api/weather/alerts", {}, "weather/tenant_alerts", {"alerts": []}),
    (weather, "daily", (URN, D1, D2), "http://wx", f"/api/weather/parcel/{URN}/daily", {"start": "2026-11-01", "end": "2026-11-02", "fill": "open_meteo"}, "weather/daily", {"days": []}),
    (soil, "summary", (URN,), "http://soil", f"/v1/soil/parcel/{URN}/summary", {}, "soil/summary", {"horizons": []}),
    (soil, "lab_analyses", (URN,), "http://soil", f"/v1/soil/parcel/{URN}/lab-analyses", {}, "soil/lab_analyses", {"analyses": []}),
    (field_ops, "operations", (URN,), "http://fo", "/api/field-operations/operations", {"parcel_id": URN, "limit": "100"}, "field_ops/operations", {"operations": []}),
    (risk, "active_alerts", (), "http://risk", "/api/risk/alerts", {"status": "active", "limit": "200"}, "risk/active_alerts", {"alerts": []}),
    (vegetation, "ndvi_history", (URN, D1, D2), "http://veg", "/api/vegetation/bff/history", {"entity_id": URN, "index_type": "NDVI", "start": "2026-11-01", "end": "2026-11-02"}, "vegetation/ndvi_history", {"points": []}),
]
IDS = [f"{c[0].__name__.rsplit('.', 1)[1]}.{c[1]}" for c in CASES]


@pytest.mark.parametrize("mod,fn,args,base,path,params,fx,empty", CASES, ids=IDS)
async def test_ok_url_query_and_identity(mod, fn, args, base, path, params, fx, empty, settings, ident, auth_headers):
    with respx.mock(assert_all_mocked=True) as m:
        route = m.get(f"{base}{path}").respond(200, json=load_fixture(fx))
        async with httpx.AsyncClient() as http:
            res = await getattr(mod, fn)(http, settings, ident, *args)
    assert res.status == "ok"
    assert res.data == load_fixture(fx)
    req = route.calls.last.request
    assert req.url.path == path
    assert dict(req.url.params) == params
    for k, v in auth_headers.items():
        assert req.headers[k] == v


@pytest.mark.parametrize(
    "mod,fn,args,base,path,params,fx,empty",
    [c for c in CASES if c[7] is not None],
    ids=[i for c, i in zip(CASES, IDS) if c[7] is not None],
)
async def test_empty_main_list(mod, fn, args, base, path, params, fx, empty, settings, ident):
    with respx.mock(assert_all_mocked=True) as m:
        m.get(f"{base}{path}").respond(200, json=empty)
        async with httpx.AsyncClient() as http:
            res = await getattr(mod, fn)(http, settings, ident, *args)
    assert res.status == "empty"
    assert res.data == empty


async def test_missing_main_key_stays_ok(settings, ident):
    with respx.mock(assert_all_mocked=True) as m:
        m.get("http://ch/api/crop-health/assessments/latest").respond(200, json={})
        async with httpx.AsyncClient() as http:
            res = await crop_health.latest(http, settings, ident, "p1")
    assert res.status == "ok"


async def test_soil_summary_404_is_empty(settings, ident):
    with respx.mock(assert_all_mocked=True) as m:
        m.get(f"http://soil/v1/soil/parcel/{URN}/summary").respond(404)
        async with httpx.AsyncClient() as http:
            res = await soil.summary(http, settings, ident, URN)
    assert res.status == "empty"


async def test_upstream_500_is_failed(settings, ident):
    with respx.mock(assert_all_mocked=True) as m:
        m.get("http://risk/api/risk/alerts").respond(500)
        async with httpx.AsyncClient() as http:
            res = await risk.active_alerts(http, settings, ident)
    assert res.status == "failed"
