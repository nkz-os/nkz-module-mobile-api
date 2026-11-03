import httpx
import pytest

PATH = "/api/mobile/parcels"
P = "urn:ngsi-ld:AgriParcel:"
PARCELS = {"parcels": [
    {"parcelId": "p1", "parcelName": "Norte", "hasData": True, "overallSeverity": "MEDIUM",
     "cropName": "Wheat", "phenologyStage": "tillering", "freshness": "fresh"},
]}
RISK = {"alerts": []}
WX = {"alerts": []}


@pytest.fixture
def upstream(respx_mock):
    return {
        "parcels": respx_mock.get("http://ch/api/crop-health/parcels").mock(
            return_value=httpx.Response(200, json=PARCELS)),
        "risk": respx_mock.get("http://risk/api/risk/alerts").mock(
            return_value=httpx.Response(200, json=RISK)),
        "wx": respx_mock.get("http://wx/api/weather/alerts").mock(
            return_value=httpx.Response(200, json=WX)),
    }


def test_parcels_contract(client, auth_headers, upstream):
    r = client.get(PATH, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 1 and body["sources"] == {"cropHealth": "ok", "risk": "empty"}
    row = body["parcels"][0]
    assert row["parcelId"] == P + "p1" and row["overall"]["level"] == "warn"
    assert row["stage"] == "tillering"
    assert upstream["parcels"].calls[0].request.headers["X-Tenant-ID"] == "acmefarm"


def test_cached_composed_and_stored_for_reuse(client, auth_headers, upstream):
    client.get(PATH, headers=auth_headers)
    client.get(PATH, headers=auth_headers)
    assert upstream["parcels"].call_count == 1 and upstream["risk"].call_count == 1
    assert client.app.state.cache_parcels.get("acmefarm", "ch:parcels").data == PARCELS


def test_reuses_parcels_cached_by_today(client, auth_headers, upstream):
    client.get("/api/mobile/today", headers=auth_headers)
    assert upstream["parcels"].call_count == 1
    r = client.get(PATH, headers=auth_headers)
    assert r.status_code == 200 and r.json()["parcels"][0]["parcelId"] == P + "p1"
    assert upstream["parcels"].call_count == 1
    assert upstream["risk"].call_count == 2  # risk is always fetched


def test_risk_raises_overall(client, auth_headers, upstream):
    upstream["risk"].mock(return_value=httpx.Response(200, json={"alerts": [
        {"id": "a1", "severity": "critical", "status": "active", "alertType": "mildew",
         "refEntity": P + "p1"}]}))
    row = client.get(PATH, headers=auth_headers).json()["parcels"][0]
    assert row["overall"]["level"] == "bad"
    assert row["overall"]["messageKey"] == "state.risks.treat"


def test_crop_health_failure_not_cached_in_shared_slot(client, auth_headers, upstream):
    upstream["parcels"].mock(return_value=httpx.Response(500))
    r = client.get(PATH, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["sources"]["cropHealth"] == "failed" and r.json()["parcels"] == []
    assert client.app.state.cache_parcels.get("acmefarm", "ch:parcels") is None


def test_failed_result_not_served_from_cache(client, auth_headers, upstream):
    upstream["parcels"].mock(return_value=httpx.Response(500))
    assert client.get(PATH, headers=auth_headers).json()["sources"]["cropHealth"] == "failed"
    upstream["parcels"].mock(return_value=httpx.Response(200, json=PARCELS))
    r = client.get(PATH, headers=auth_headers)
    assert r.json()["sources"]["cropHealth"] == "ok" and len(r.json()["parcels"]) == 1
