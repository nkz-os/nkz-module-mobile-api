from datetime import datetime, timezone

import httpx
import pytest
from nkz_platform_sdk.orion import OrionClient

from app.sources import orion

URN = "urn:ngsi-ld:AgriParcel:p1"
ENT = "http://orion:1026/ngsi-ld/v1/entities"
CROP_URN = "urn:ngsi-ld:AgriCrop:1"


@pytest.fixture
def oc(settings_env):
    return OrionClient("acmefarm", base_url="http://orion:1026")


async def test_parcel_exists_ok(respx_mock, oc):
    route = respx_mock.get(f"{ENT}/{URN}").mock(return_value=httpx.Response(200, json={"id": URN}))
    res = await orion.parcel_exists(oc, URN)
    assert res.status == "ok" and res.data["id"] == URN
    req = route.calls[0].request
    assert req.headers["NGSILD-Tenant"] == "acmefarm"
    assert req.url.params["options"] == "keyValues"


async def test_parcel_exists_404_empty(respx_mock, oc):
    respx_mock.get(f"{ENT}/{URN}").mock(return_value=httpx.Response(404))
    assert (await orion.parcel_exists(oc, URN)).status == "empty"


async def test_parcel_exists_500_failed(respx_mock, oc):
    respx_mock.get(f"{ENT}/{URN}").mock(return_value=httpx.Response(500))
    res = await orion.parcel_exists(oc, URN)
    assert res.status == "failed" and res.error == "HTTPStatusError"


async def test_parcel_exists_timeout(respx_mock, oc):
    respx_mock.get(f"{ENT}/{URN}").mock(side_effect=httpx.ReadTimeout("x"))
    assert (await orion.parcel_exists(oc, URN)).status == "timeout"


TIMELINE = {"current": {"species": "TRZAX", "crop_id": CROP_URN,
                        "start": {"date": "2026-10-20", "provenance": "actual"}}}


async def test_crop_ok_with_variety(respx_mock, oc, monkeypatch):
    async def fake(tenant, urn, *a, **k):
        assert (tenant, urn) == ("acmefarm", URN)
        return TIMELINE
    monkeypatch.setattr(orion, "fetch_crop_timeline", fake)
    respx_mock.get(f"{ENT}/{CROP_URN}").mock(return_value=httpx.Response(200, json={"variety": "Marius"}))
    res = await orion.crop("acmefarm", URN, oc)
    assert res.status == "ok"
    assert res.data == {"timeline": TIMELINE, "variety": "Marius"}


async def test_crop_variety_failure_does_not_degrade(respx_mock, oc, monkeypatch):
    async def fake(*a, **k):
        return TIMELINE
    monkeypatch.setattr(orion, "fetch_crop_timeline", fake)
    respx_mock.get(f"{ENT}/{CROP_URN}").mock(return_value=httpx.Response(500))
    res = await orion.crop("acmefarm", URN, oc)
    assert res.status == "ok" and res.data["variety"] is None


async def test_crop_no_current_crop_skips_lookup(oc, monkeypatch):
    async def fake(*a, **k):
        return {"current": None}
    monkeypatch.setattr(orion, "fetch_crop_timeline", fake)
    res = await orion.crop("acmefarm", URN, oc)
    assert res.status == "ok" and res.data["variety"] is None


async def test_crop_none_is_failed(oc, monkeypatch):
    async def fake(*a, **k):
        return None
    monkeypatch.setattr(orion, "fetch_crop_timeline", fake)
    res = await orion.crop("acmefarm", URN, oc)
    assert res.status == "failed" and res.error == "timeline"


async def test_crop_exception_failed(oc, monkeypatch):
    async def fake(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(orion, "fetch_crop_timeline", fake)
    res = await orion.crop("acmefarm", URN, oc)
    assert res.status == "failed" and res.error == "RuntimeError"


Q_BASE = f'(hasAgriParcel=="{URN}"|refAgriParcel=="{URN}");imageUrl'


async def test_photos_query_requires_image_and_sorts(respx_mock, oc):
    route = respx_mock.get(ENT).mock(return_value=httpx.Response(200, json=[
        {"id": "a", "imageUrl": "u1", "dateObserved": "2026-10-01T10:00:00Z"},
        {"id": "b", "dateObserved": "2026-10-09T10:00:00Z"},
        {"id": "c", "imageUrl": "u3", "dateObserved": "2026-10-05T10:00:00Z"},
    ]))
    res = await orion.photos(oc, URN, None, 20)
    assert res.status == "ok"
    assert [e["id"] for e in res.data] == ["c", "a"]
    assert route.call_count == 1
    p = route.calls[0].request.url.params
    assert p["type"] == "AgriParcelRecord" and p["limit"] == "20" and p["options"] == "keyValues"
    assert p["q"] == Q_BASE and p["offset"] == "0"


async def test_photos_paginates_then_keeps_newest(respx_mock, oc):
    pages = {"0": [{"id": "a", "imageUrl": "u", "dateObserved": "2026-10-01T00:00:00Z"},
                   {"id": "b", "imageUrl": "u", "dateObserved": "2026-10-02T00:00:00Z"}],
             "2": [{"id": "c", "imageUrl": "u", "dateObserved": "2026-10-09T00:00:00Z"}]}
    route = respx_mock.get(ENT).mock(side_effect=lambda r: httpx.Response(
        200, json=pages[r.url.params["offset"]]))
    res = await orion.photos(oc, URN, None, 2)
    assert route.call_count == 2
    assert [e["id"] for e in res.data] == ["c", "b"]


async def test_photos_stops_at_500_rows(respx_mock, oc):
    sizes = []

    def handler(r):
        sizes.append((r.url.params["offset"], r.url.params["limit"]))
        n = int(r.url.params["limit"])
        return httpx.Response(200, json=[{"id": "x", "imageUrl": "u", "dateObserved": "2026-10-01T00:00:00Z"}] * n)
    respx_mock.get(ENT).mock(side_effect=handler)
    await orion.photos(oc, URN, None, 200)
    assert sizes == [("0", "200"), ("200", "200"), ("400", "100")]


async def test_photos_since_quoted(respx_mock, oc):
    route = respx_mock.get(ENT).mock(return_value=httpx.Response(200, json=[
        {"id": "a", "imageUrl": "u", "dateObserved": "2026-10-05T00:00:00Z"}]))
    since = datetime(2026, 10, 1, tzinfo=timezone.utc)
    res = await orion.photos(oc, URN, since, 5)
    assert res.status == "ok"
    assert route.calls[0].request.url.params["q"] == Q_BASE + ';dateObserved>="2026-10-01T00:00:00Z"'


async def test_photos_both_empty(respx_mock, oc):
    respx_mock.get(ENT).mock(return_value=httpx.Response(200, json=[]))
    assert (await orion.photos(oc, URN, None, 5)).status == "empty"


async def test_photos_no_imageurl_is_empty(respx_mock, oc):
    respx_mock.get(ENT).mock(return_value=httpx.Response(200, json=[{"id": "a"}]))
    assert (await orion.photos(oc, URN, None, 5)).status == "empty"


async def test_photos_500_failed(respx_mock, oc):
    respx_mock.get(ENT).mock(return_value=httpx.Response(500))
    res = await orion.photos(oc, URN, None, 5)
    assert res.status == "failed" and res.error == "HTTPStatusError"
