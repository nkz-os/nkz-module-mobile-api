from datetime import date, timedelta, timezone, datetime

import httpx
import pytest

B = "/api/mobile/parcels"
URN = "urn:ngsi-ld:AgriParcel:p1"
ENT = "http://orion:1026/ngsi-ld/v1/entities"


@pytest.fixture(autouse=True)
def parcel(respx_mock):
    return respx_mock.get(f"{ENT}/{URN}").mock(return_value=httpx.Response(200, json={"id": URN}))


# --- photos -------------------------------------------------------------------

def _rec(i, url="/api/field-images/k1", **kw):
    return {"id": f"urn:ngsi-ld:AgriParcelRecord:{i}", "imageUrl": url,
            "dateObserved": "2026-10-05T10:00:00Z", **kw}


def test_photos_mapping(client, auth_headers, respx_mock):
    def handler(request):
        return httpx.Response(200, json=[
            _rec(1, note="n", tag="t", accuracy=4.5,
                 location={"type": "Point", "coordinates": [-1.6, 42.8]}),
            _rec(2, url="https://files.example.org/api/field-images/k2?x=1"),
            _rec(3, url=None),
            {"imageUrl": "/api/field-images/k4", "dateObserved": "2026-10-01T00:00:00Z"},
        ])
    route = respx_mock.get(ENT).mock(side_effect=handler)
    r = client.get(f"{B}/p1/photos", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 1
    ph = body["photos"]
    assert [p["id"] for p in ph] == ["urn:ngsi-ld:AgriParcelRecord:1", "urn:ngsi-ld:AgriParcelRecord:2"]
    assert ph[0] == {"id": "urn:ngsi-ld:AgriParcelRecord:1", "imageUrl": "/api/field-images/k1",
                     "capturedAt": "2026-10-05T10:00:00Z", "note": "n", "tag": "t",
                     "location": [-1.6, 42.8], "accuracyM": 4.5}
    assert ph[1]["imageUrl"] == "/api/field-images/k2"
    assert ph[1]["note"] is None and ph[1]["location"] is None and ph[1]["accuracyM"] is None
    assert route.calls[0].request.url.params["limit"] == "50"
    q = route.calls[0].request.url.params["q"]
    assert q == f'(hasAgriParcel=="{URN}"|refAgriParcel=="{URN}");imageUrl'
    assert route.call_count == 1  # fewer rows than the page size: no second page


def test_photos_since_and_limit_forwarded(client, auth_headers, respx_mock):
    route = respx_mock.get(ENT).mock(return_value=httpx.Response(200, json=[_rec(1)]))
    r = client.get(f"{B}/{URN}/photos?since=2026-10-01T00:00:00Z&limit=7", headers=auth_headers)
    assert r.status_code == 200
    p = route.calls[0].request.url.params
    assert p["limit"] == "7" and 'dateObserved>="2026-10-01T00:00:00Z"' in p["q"]


def test_photos_paginate_and_cut_newest_first(client, auth_headers, respx_mock):
    def page(request):
        off = int(request.url.params["offset"])
        assert request.url.params["limit"] == "2"
        rows = {0: [_rec(1, dateObserved="2026-10-01T00:00:00Z"), _rec(2, dateObserved="2026-10-03T00:00:00Z")],
                2: [_rec(3, dateObserved="2026-10-05T00:00:00Z")]}[off]
        return httpx.Response(200, json=rows)
    route = respx_mock.get(ENT).mock(side_effect=page)
    r = client.get(f"{B}/p1/photos?limit=2", headers=auth_headers)
    assert route.call_count == 2
    assert [p["id"][-1] for p in r.json()["photos"]] == ["3", "2"]  # newest first, then cut to limit


def test_photos_page_cap_500_rows(client, auth_headers, respx_mock):
    route = respx_mock.get(ENT).mock(side_effect=lambda req: httpx.Response(
        200, json=[_rec(i) for i in range(200)]))
    r = client.get(f"{B}/p1/photos?limit=200", headers=auth_headers)
    assert r.status_code == 200 and len(r.json()["photos"]) == 200
    assert route.call_count == 3  # 200 + 200 + 200 reaches the 500-row cap


@pytest.mark.parametrize("qs", ["limit=0", "limit=201", "limit=x", "since=yesterday"])
def test_photos_400(client, auth_headers, qs):
    r = client.get(f"{B}/p1/photos?{qs}", headers=auth_headers)
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_since" if qs.startswith("since") else "invalid_limit"}


def test_photos_source_failure_is_empty_list(client, auth_headers, respx_mock):
    respx_mock.get(ENT).mock(return_value=httpx.Response(500))
    r = client.get(f"{B}/p1/photos", headers=auth_headers)
    assert r.status_code == 200 and r.json()["photos"] == [] and r.json()["source"] == "failed"


def test_photos_source_ok_and_empty(client, auth_headers, respx_mock):
    respx_mock.get(ENT).mock(return_value=httpx.Response(200, json=[_rec(1)]))
    assert client.get(f"{B}/p1/photos", headers=auth_headers).json()["source"] == "ok"
    respx_mock.get(ENT).mock(return_value=httpx.Response(200, json=[]))
    assert client.get(f"{B}/p1/photos", headers=auth_headers).json()["source"] == "empty"


def test_photos_without_date_dropped(client, auth_headers, respx_mock):
    nodate = {"id": "urn:ngsi-ld:AgriParcelRecord:9", "imageUrl": "/api/field-images/k9"}
    respx_mock.get(ENT).mock(return_value=httpx.Response(200, json=[nodate, _rec(1)]))
    ph = client.get(f"{B}/p1/photos", headers=auth_headers).json()["photos"]
    assert [p["id"] for p in ph] == ["urn:ngsi-ld:AgriParcelRecord:1"]


# --- series -------------------------------------------------------------------

def _today():
    return datetime.now(timezone.utc).date()


def test_series_water_balance_uses_short_id(client, auth_headers, respx_mock):
    route = respx_mock.get("http://ch/api/crop-health/assessments/history").mock(
        return_value=httpx.Response(200, json={"points": [
            {"date": "2026-11-02", "balance": 4}, {"date": "2026-11-01", "balance": 3}]}))
    r = client.get(f"{B}/{URN}/series?metric=water_balance&days=30", headers=auth_headers)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["metric"] == "water_balance" and b["unit"] == "mm" and b["days"] == 30
    assert [p["date"] for p in b["points"]] == ["2026-11-01", "2026-11-02"]
    assert b["source"] == "ok"
    p = route.calls[0].request.url.params
    assert p["parcelId"] == "p1" and p["days"] == "30"


def test_series_rain_dates(client, auth_headers, respx_mock):
    route = respx_mock.get(f"http://wx/api/weather/parcel/{URN}/daily").mock(
        return_value=httpx.Response(200, json={"days": [{"date": "2026-11-01", "precip_mm": 1.2}]}))
    r = client.get(f"{B}/p1/series?metric=rain&days=7", headers=auth_headers)
    assert r.status_code == 200 and r.json()["points"][0]["value"] == 1.2
    p = route.calls[0].request.url.params
    assert p["end"] == _today().isoformat() and p["start"] == (_today() - timedelta(days=6)).isoformat()


def test_series_vigor(client, auth_headers, respx_mock):
    route = respx_mock.get("http://veg/api/vegetation/bff/history").mock(
        return_value=httpx.Response(200, json={"points": [{"date": "2026-11-01", "mean": 0.61}]}))
    r = client.get(f"{B}/p1/series?metric=vigor&days=90", headers=auth_headers)
    assert r.json()["unit"] == "ndvi" and r.json()["points"][0]["value"] == 0.61
    assert route.calls[0].request.url.params["entity_id"] == URN
    assert route.calls[0].request.url.params["start"] == (_today() - timedelta(days=89)).isoformat()


def test_series_empty_history(client, auth_headers, respx_mock):
    respx_mock.get("http://ch/api/crop-health/assessments/history").mock(
        return_value=httpx.Response(200, json={"points": []}))
    r = client.get(f"{B}/p1/series?metric=cwsi&days=7", headers=auth_headers)
    assert r.json()["source"] == "empty" and r.json()["points"] == []


def test_series_source_failed_still_200(client, auth_headers, respx_mock):
    respx_mock.get(f"http://wx/api/weather/parcel/{URN}/daily").mock(return_value=httpx.Response(500))
    r = client.get(f"{B}/p1/series?metric=tmax&days=7", headers=auth_headers)
    assert r.status_code == 200 and r.json()["source"] == "failed"


@pytest.mark.parametrize("qs", ["metric=nope&days=7", "metric=rain&days=14", "metric=rain",
                                "days=7", "metric=rain&days=x"])
def test_series_400(client, auth_headers, qs):
    r = client.get(f"{B}/p1/series?{qs}", headers=auth_headers)
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_metric" if qs in ("metric=nope&days=7", "days=7") else "invalid_days"}


def test_series_cached(client, auth_headers, respx_mock):
    route = respx_mock.get("http://ch/api/crop-health/assessments/history").mock(
        return_value=httpx.Response(200, json={"points": [{"date": "2026-11-01", "balance": 1}]}))
    for _ in range(2):
        client.get(f"{B}/p1/series?metric=water_balance&days=7", headers=auth_headers)
    assert route.call_count == 1
    assert client.app.state.cache_series.get("acmefarm", f"series:{URN}:water_balance:7") is not None


def test_series_failed_not_cached(client, auth_headers, respx_mock):
    route = respx_mock.get("http://ch/api/crop-health/assessments/history")
    route.mock(return_value=httpx.Response(500))
    assert client.get(f"{B}/p1/series?metric=cwsi&days=7", headers=auth_headers).json()["source"] == "failed"
    route.mock(return_value=httpx.Response(200, json={"points": [{"date": "2026-11-01", "cwsi": 0.3}]}))
    r = client.get(f"{B}/p1/series?metric=cwsi&days=7", headers=auth_headers)
    assert r.json()["source"] == "ok"


BAD = "urn:x%2F..%2F..%2Finternal"


def test_invalid_parcel_id_400_everywhere(client, auth_headers):
    for path in (f"{B}/{BAD}/photos", f"{B}/{BAD}/series?metric=rain&days=7",
                 f"/api/mobile/briefing/{BAD}"):
        r = client.get(path, headers=auth_headers)
        assert r.status_code == 400 and r.json() == {"error": "invalid_parcel_id"}, path


def test_photos_unknown_parcel_404(client, auth_headers, respx_mock, parcel):
    parcel.mock(return_value=httpx.Response(404))
    q = respx_mock.get(ENT).mock(return_value=httpx.Response(200, json=[_rec(1)]))
    r = client.get(f"{B}/p1/photos", headers=auth_headers)
    assert r.status_code == 404 and r.json() == {"error": "parcel_not_found"}
    assert q.call_count == 0


def test_photos_parcel_check_failure_continues(client, auth_headers, respx_mock, parcel):
    parcel.mock(return_value=httpx.Response(500))
    respx_mock.get(ENT).mock(return_value=httpx.Response(200, json=[_rec(1)]))
    r = client.get(f"{B}/p1/photos", headers=auth_headers)
    assert r.status_code == 200 and r.json()["source"] == "ok"


def test_series_unknown_parcel_404(client, auth_headers, respx_mock, parcel):
    parcel.mock(return_value=httpx.Response(404))
    h = respx_mock.get("http://ch/api/crop-health/assessments/history")
    r = client.get(f"{B}/p1/series?metric=cwsi&days=7", headers=auth_headers)
    assert r.status_code == 404 and r.json() == {"error": "parcel_not_found"}
    assert h.call_count == 0


def test_series_parcel_check_failure_continues(client, auth_headers, respx_mock, parcel):
    parcel.mock(side_effect=httpx.ReadTimeout("x"))
    respx_mock.get("http://ch/api/crop-health/assessments/history").mock(
        return_value=httpx.Response(200, json={"points": [{"date": "2026-11-01", "cwsi": 0.3}]}))
    r = client.get(f"{B}/p1/series?metric=cwsi&days=7", headers=auth_headers)
    assert r.status_code == 200 and r.json()["source"] == "ok"
