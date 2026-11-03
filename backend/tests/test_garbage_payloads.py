"""Every source returns malformed JSON of the wrong shape: endpoints still answer 200."""

import httpx
import pytest

from app.schemas import BriefingV1, ParcelsV1, PhotosV1, SeriesV1, TodayV1
from app.sources import orion

URN = "urn:ngsi-ld:AgriParcel:p1"
P = "/api/mobile"
UPSTREAM = r"http://(ch|wx|soil|fo|risk|veg)/.*"
ORION = r"http://orion:1026/.*"

KEYS = ("assessments", "risks", "alerts", "operations", "estimates", "horizons", "analyses",
        "forecast", "days", "points", "parcels", "semaphores", "weather", "nextJob",
        "plannedCrop", "surprise", "freshness", "timeline", "soilProperties", "gdd",
        "currentStage", "usdaTextureClass", "status", "detail", "names")
BAD_ITEM = {"severity": ["u"], "risk_level": {"x": 1}, "refEntity": 5, "id": 3, "kind": ["a"],
            "when": {}, "parcelId": ["p"], "imageUrl": 3, "dateObserved": 7, "value": "x"}

VARIANTS = {
    "list_of_junk": ["x", 1, None, {"a": 1}, [1]],
    "strings": {k: "str" for k in KEYS},
    "numbers": {k: 12.5 for k in KEYS},
    "dicts_of_lists": {k: {"a": [1]} for k in KEYS},
    "lists_of_junk": {k: ["x", 1, None, [], BAD_ITEM] for k in KEYS},
    "lists_of_dicts": {k: [BAD_ITEM, {"severity": None, "kind": None}] for k in KEYS},
}


@pytest.fixture(params=sorted(VARIANTS))
def garbage(request, respx_mock, monkeypatch):
    payload = VARIANTS[request.param]
    respx_mock.get(url__regex=UPSTREAM).mock(return_value=httpx.Response(200, json=payload))
    respx_mock.get(url__regex=ORION).mock(return_value=httpx.Response(200, json=payload))

    async def timeline(*a, **k):
        return payload
    monkeypatch.setattr(orion, "fetch_crop_timeline", timeline)
    return payload


def test_briefing_garbage(client, auth_headers, garbage):
    r = client.get(f"{P}/briefing/p1", headers=auth_headers)
    assert r.status_code == 200, r.text
    BriefingV1.model_validate(r.json())


def test_today_garbage(client, auth_headers, garbage):
    r = client.get(f"{P}/today", headers=auth_headers)
    assert r.status_code == 200, r.text
    TodayV1.model_validate(r.json())


def test_parcels_garbage(client, auth_headers, garbage):
    r = client.get(f"{P}/parcels", headers=auth_headers)
    assert r.status_code == 200, r.text
    ParcelsV1.model_validate(r.json())


def test_photos_garbage(client, auth_headers, garbage):
    r = client.get(f"{P}/parcels/p1/photos", headers=auth_headers)
    assert r.status_code == 200, r.text
    PhotosV1.model_validate(r.json())


@pytest.mark.parametrize("metric", ["water_balance", "cwsi", "rain", "tmax", "tmin", "vigor"])
def test_series_garbage(client, auth_headers, garbage, metric):
    r = client.get(f"{P}/parcels/p1/series?metric={metric}&days=7", headers=auth_headers)
    assert r.status_code == 200, r.text
    SeriesV1.model_validate(r.json())
