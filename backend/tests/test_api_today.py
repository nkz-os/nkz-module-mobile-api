import httpx
import pytest

PATH = "/api/mobile/today"
P = "urn:ngsi-ld:AgriParcel:"

PARCELS = {"parcels": [
    {"parcelId": "p1", "parcelName": "Norte", "hasData": True, "cropStatus": "active",
     "nextJob": {"kind": "irrigate", "when": "today", "detail": {"mm": 10}}},
    {"parcelId": "p2", "parcelName": "Sur", "hasData": True, "cropStatus": "none", "nextJob": None},
]}
RISK = {"alerts": [{"id": "a1", "category": {"type": "Property", "value": "disease"},
                    "alertType": {"type": "Property", "value": "mildew"},
                    "severity": {"type": "Property", "value": "high"},
                    "status": {"type": "Property", "value": "active"},
                    "refEntity": {"type": "Relationship", "object": P + "p1"}}]}
WX = {"alerts": [{"id": "w1", "severity": "severe", "description": "Frost",
                  "validFrom": "2026-11-04T00:00:00Z", "validTo": "2026-11-04T09:00:00Z"}]}


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


def test_today_contract_and_identity(client, auth_headers, upstream):
    r = client.get(PATH, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 1
    assert body["sources"] == {"cropHealth": "ok", "risk": "ok", "weather": "ok"}
    assert [c["id"] for c in body["cards"]] == ["a1", "w1", f"job:{P}p1:irrigate"]
    assert body["summary"] == {"alerts": 2, "jobsToday": 1, "surprises": 0, "noData": 0}
    assert upstream["parcels"].calls[0].request.headers["X-Tenant-ID"] == "acmefarm"


def test_cached_and_parcels_stored_for_reuse(client, auth_headers, upstream):
    client.get(PATH, headers=auth_headers)
    client.get(PATH, headers=auth_headers)
    assert upstream["parcels"].call_count == 1
    stored = client.app.state.cache_parcels.get("acmefarm", "ch:parcels")
    assert stored.status == "ok" and stored.data == PARCELS
    # another language is a separate entry
    client.get(PATH + "?lang=en", headers=auth_headers)
    assert upstream["parcels"].call_count == 2


def test_risk_failure_keeps_other_cards(client, auth_headers, upstream):
    upstream["risk"].mock(return_value=httpx.Response(500))
    r = client.get(PATH, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["sources"]["risk"] == "failed" and body["sources"]["cropHealth"] == "ok"
    assert [c["id"] for c in body["cards"]] == ["w1", f"job:{P}p1:irrigate"]


def test_failed_parcels_not_stored(client, auth_headers, upstream):
    upstream["parcels"].mock(return_value=httpx.Response(500))
    r = client.get(PATH, headers=auth_headers)
    assert r.json()["sources"]["cropHealth"] == "failed"
    assert client.app.state.cache_parcels.get("acmefarm", "ch:parcels") is None


def test_empty_parcels_stored(client, auth_headers, upstream):
    upstream["parcels"].mock(return_value=httpx.Response(404))
    r = client.get(PATH, headers=auth_headers)
    assert r.json()["sources"]["cropHealth"] == "empty"
    assert client.app.state.cache_parcels.get("acmefarm", "ch:parcels").status == "empty"


def test_invalid_lang_400(client, auth_headers):
    assert client.get(PATH + "?lang=xx", headers=auth_headers).status_code == 400


def test_requires_identity(client, upstream):
    assert client.get(PATH).status_code in (401, 403)
