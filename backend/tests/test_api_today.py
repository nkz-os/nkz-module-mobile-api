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


REPORT = {"reportId": "r-1", "weekStart": "2026-11-02", "status": "complete",
          "generatedAt": "2026-11-02T06:00:00Z", "plain": {"title": "Weekly", "body": "Calm"}}
NOTIF = "http://notif/api/notifications/weekly-report/latest"


@pytest.fixture
def admin_headers(auth_headers):
    return {**auth_headers, "X-User-Roles": "TenantAdmin"}


@pytest.fixture
def report(respx_mock):
    return respx_mock.get(NOTIF).mock(return_value=httpx.Response(200, json=REPORT))


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
    assert body["sources"] == {"cropHealth": "ok", "risk": "ok", "weather": "ok",
                               "notifications": "empty"}
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
    r = client.get(PATH + "?lang=xx", headers=auth_headers)
    assert r.status_code == 400 and r.json() == {"error": "invalid_lang"}


def test_requires_identity(client, upstream):
    assert client.get(PATH).status_code in (401, 403)


def test_degraded_today_not_cached(client, auth_headers, upstream):
    upstream["risk"].mock(return_value=httpx.Response(500))
    client.get(PATH, headers=auth_headers)
    upstream["risk"].mock(return_value=httpx.Response(200, json=RISK))
    r = client.get(PATH, headers=auth_headers)
    assert r.json()["sources"]["risk"] == "ok"
    assert client.get(PATH, headers=auth_headers).json()["sources"]["risk"] == "ok"
    assert upstream["risk"].call_count == 2  # 500, then 200 (cached afterwards)


def test_admin_gets_report_card_last(client, admin_headers, upstream, report):
    body = client.get(PATH + "?lang=en", headers=admin_headers).json()
    assert body["version"] == 1 and body["sources"]["notifications"] == "ok"
    assert body["cards"][-1]["id"] == "weekly_report:r-1"
    assert report.calls[0].request.url.params["lang"] == "en"
    assert report.calls[0].request.headers["X-Tenant-ID"] == "acmefarm"


def test_technical_consultant_gets_card(client, auth_headers, upstream, report):
    h = {**auth_headers, "X-User-Roles": "TechnicalConsultant"}
    assert client.get(PATH, headers=h).json()["cards"][-1]["kind"] == "weekly_report"


def test_farmer_no_call_no_card(client, auth_headers, upstream, report):
    body = client.get(PATH, headers=auth_headers).json()
    assert report.call_count == 0 and body["sources"]["notifications"] == "empty"
    assert all(c["kind"] != "weekly_report" for c in body["cards"])


def test_report_404_empty(client, admin_headers, upstream, report):
    report.mock(return_value=httpx.Response(404))
    body = client.get(PATH, headers=admin_headers).json()
    assert body["sources"]["notifications"] == "empty"
    assert all(c["kind"] != "weekly_report" for c in body["cards"])


def test_report_failed_no_card_not_cached(client, admin_headers, upstream, report):
    report.mock(return_value=httpx.Response(500))
    r = client.get(PATH, headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["sources"]["notifications"] == "failed" and body["sources"]["risk"] == "ok"
    assert [c["id"] for c in body["cards"]] == ["a1", "w1", f"job:{P}p1:irrigate"]
    client.get(PATH, headers=admin_headers)
    assert upstream["risk"].call_count == 2  # failed result not cached


def test_report_malformed_failed_no_500(client, admin_headers, upstream, report):
    report.mock(return_value=httpx.Response(200, json={"reportId": "r-1"}))
    r = client.get(PATH, headers=admin_headers)
    assert r.status_code == 200 and r.json()["sources"]["notifications"] == "failed"
    assert all(c["kind"] != "weekly_report" for c in r.json()["cards"])


def test_cache_not_shared_between_roles(client, admin_headers, auth_headers, upstream, report):
    first = client.get(PATH, headers=admin_headers).json()
    assert first["cards"][-1]["kind"] == "weekly_report"
    second = client.get(PATH, headers=auth_headers).json()
    assert all(c["kind"] != "weekly_report" for c in second["cards"])
    assert second["sources"]["notifications"] == "empty"
    # admin again is served from cache without a second upstream call
    client.get(PATH, headers=admin_headers)
    assert report.call_count == 1
