import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.sources import orion
from tests.helpers import load_fixture

URN = "urn:ngsi-ld:AgriParcel:p1"
ENT = "http://orion:1026/ngsi-ld/v1/entities"
PATH = "/api/mobile/briefing"
TIMELINE = {"current": {"species": "TRZAX", "start": {"date": "2026-10-20", "provenance": "actual"}}}


@pytest.fixture(autouse=True)
def timeline(monkeypatch):
    calls = []

    async def fake(tenant, urn, *a, **k):
        calls.append((tenant, urn))
        return TIMELINE
    monkeypatch.setattr(orion, "fetch_crop_timeline", fake)
    return calls


@pytest.fixture
def upstream(respx_mock):
    routes = {
        "orion": respx_mock.get(f"{ENT}/{URN}").mock(return_value=httpx.Response(200, json={"id": URN, "name": "Norte"})),
        "latest": respx_mock.get("http://ch/api/crop-health/assessments/latest").mock(
            return_value=httpx.Response(200, json=load_fixture("crop_health/latest"))),
        "diseases": respx_mock.get("http://ch/api/crop-health/diseases/active").mock(
            return_value=httpx.Response(200, json=load_fixture("crop_health/diseases_active"))),
        "pheno": respx_mock.get(f"http://ch/api/crop-health/parcels/{URN}/phenology-status").mock(
            return_value=httpx.Response(200, json=load_fixture("crop_health/phenology"))),
        "yield": respx_mock.get(f"http://ch/api/crop-health/parcels/{URN}/yield-forecast").mock(
            return_value=httpx.Response(200, json=load_fixture("crop_health/yield_forecast"))),
        "agro": respx_mock.get(f"http://wx/api/weather/parcel/{URN}/agro-status").mock(
            return_value=httpx.Response(200, json=load_fixture("weather/agro_status"))),
        "fc": respx_mock.get(f"http://wx/api/weather/parcel/{URN}/forecast").mock(
            return_value=httpx.Response(200, json=load_fixture("weather/forecast"))),
        "wxa": respx_mock.get(f"http://wx/api/weather/parcel/{URN}/alerts").mock(
            return_value=httpx.Response(200, json=load_fixture("weather/parcel_alerts"))),
        "soil": respx_mock.get(f"http://soil/v1/soil/parcel/{URN}/summary").mock(
            return_value=httpx.Response(200, json=load_fixture("soil/summary"))),
        "labs": respx_mock.get(f"http://soil/v1/soil/parcel/{URN}/lab-analyses").mock(
            return_value=httpx.Response(200, json=load_fixture("soil/lab_analyses"))),
        "ops": respx_mock.get("http://fo/api/field-operations/operations").mock(
            return_value=httpx.Response(200, json=load_fixture("field_ops/operations"))),
        "risk": respx_mock.get("http://risk/api/risk/alerts").mock(
            return_value=httpx.Response(200, json=load_fixture("risk/active_alerts"))),
    }
    return routes


def total_calls(routes):
    return sum(r.call_count for r in routes.values())


def test_urn_and_short_id_same_body(client, auth_headers, upstream):
    a = client.get(f"{PATH}/{URN}", headers=auth_headers)
    assert a.status_code == 200, a.text
    b = client.get(f"{PATH}/p1?lang=es", headers=auth_headers)
    assert b.status_code == 200
    body = a.json()
    assert body["parcelId"] == URN and body["parcelName"] == "Norte" and body["version"] == 1
    assert body["lang"] == "es" and body["crop"]["status"] == "active"
    assert body["sources"]["cropHealth"] == "ok"
    assert {k: v for k, v in b.json().items() if k != "generatedAt"} == \
           {k: v for k, v in body.items() if k != "generatedAt"}
    # crop-health gets the short id, others the URN
    assert upstream["latest"].calls[0].request.url.params["parcelId"] == "p1"
    assert upstream["ops"].calls[0].request.url.params["parcel_id"] == URN
    # identity forwarded
    assert upstream["latest"].calls[0].request.headers["X-Tenant-ID"] == "acmefarm"


def test_response_is_contract_shape(client, auth_headers, upstream):
    body = client.get(f"{PATH}/p1", headers=auth_headers).json()
    contract = json.loads((Path(__file__).parent / "fixtures/contract/briefing_v1.json").read_text())
    assert set(body) == set(contract)
    assert set(body["sources"]) == set(contract["sources"])


def test_unknown_parcel_404(client, auth_headers, upstream, respx_mock):
    upstream["orion"].mock(return_value=httpx.Response(404))
    r = client.get(f"{PATH}/p1", headers=auth_headers)
    assert r.status_code == 404 and r.json() == {"error": "parcel_not_found"}
    assert upstream["latest"].call_count == 0


def test_orion_500_degrades_not_404(client, auth_headers, upstream, monkeypatch):
    upstream["orion"].mock(return_value=httpx.Response(500))

    async def none(*a, **k):
        return None
    monkeypatch.setattr(orion, "fetch_crop_timeline", none)
    r = client.get(f"{PATH}/p1", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["crop"]["status"] == "unknown" and body["sources"]["cropHealth"] == "failed"
    assert body["parcelName"] == "Norte"  # from the crop-health assessment
    assert body["weather"] is not None


def test_parcel_name_null_when_no_source_has_it(client, auth_headers, upstream, monkeypatch):
    upstream["orion"].mock(return_value=httpx.Response(500))
    upstream["latest"].mock(return_value=httpx.Response(404))
    upstream["agro"].mock(return_value=httpx.Response(404))
    r = client.get(f"{PATH}/p1", headers=auth_headers)
    assert r.status_code == 200 and r.json()["parcelName"] is None


def test_forecast_from_real_estimate_shape(client, auth_headers, upstream):
    f = client.get(f"{PATH}/p1", headers=auth_headers).json()["forecast"]
    assert f["yield"] == {"value": 5.2, "unit": "t/ha", "low": 4.1, "high": 6.3}


def test_cached_within_ttl_and_per_tenant(client, auth_headers, upstream, timeline):
    client.get(f"{PATH}/p1", headers=auth_headers)
    n = total_calls(upstream)
    client.get(f"{PATH}/p1", headers=auth_headers)
    assert total_calls(upstream) == n
    other = {**auth_headers, "X-Tenant-ID": "othertenant"}
    r = client.get(f"{PATH}/p1", headers=other)
    assert r.status_code == 200
    assert total_calls(upstream) > n  # other tenant never reads acmefarm's entry
    assert ("othertenant", URN) in timeline


def test_lang_validation_and_cache_key(client, auth_headers, upstream):
    assert client.get(f"{PATH}/p1?lang=fr", headers=auth_headers).status_code == 400
    assert client.get(f"{PATH}/p1?lang=en", headers=auth_headers).json()["lang"] == "en"


def test_requires_user_id(client, auth_headers, upstream):
    h = {k: v for k, v in auth_headers.items() if k != "X-User-ID"}
    assert client.get(f"{PATH}/p1", headers=h).status_code == 401
