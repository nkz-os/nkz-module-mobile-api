import asyncio
import time

import httpx
from fastapi.testclient import TestClient
import pytest
import respx

from app.sources import base
from app.sources.base import SourceResult, call, gather_with_budget

URL = "http://src/x"


def _factory(http):
    return lambda: http.get(URL)


@respx.mock(assert_all_mocked=True)
async def test_200_ok(respx_mock):
    respx_mock.get(URL).respond(200, json={"a": 1})
    async with httpx.AsyncClient() as http:
        r = await call("s", _factory(http), timeout_s=1)
    assert r == SourceResult("ok", {"a": 1}, None)


@respx.mock(assert_all_mocked=True)
async def test_bad_json(respx_mock):
    respx_mock.get(URL).respond(200, content=b"<html>")
    async with httpx.AsyncClient() as http:
        r = await call("s", _factory(http), timeout_s=1)
    assert (r.status, r.error) == ("failed", "bad_json")


@respx.mock(assert_all_mocked=True)
async def test_404_empty_and_custom_empty_on(respx_mock):
    respx_mock.get(URL).respond(404)
    async with httpx.AsyncClient() as http:
        assert (await call("s", _factory(http), timeout_s=1)).status == "empty"
        r = await call("s", _factory(http), timeout_s=1, empty_on=(204,))
    assert (r.status, r.error) == ("failed", "http_404")


@pytest.mark.parametrize("code", [401, 403])
@respx.mock(assert_all_mocked=True)
async def test_auth_failed(respx_mock, code):
    respx_mock.get(URL).respond(code)
    async with httpx.AsyncClient() as http:
        r = await call("s", _factory(http), timeout_s=1)
    assert (r.status, r.error) == ("failed", "auth")


@respx.mock(assert_all_mocked=True)
async def test_500_failed(respx_mock):
    respx_mock.get(URL).respond(500)
    async with httpx.AsyncClient() as http:
        r = await call("s", _factory(http), timeout_s=1)
    assert (r.status, r.error) == ("failed", "http_500")


# assert_all_called=False: the call is cancelled by wait_for before respx sees it
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_slow_upstream_times_out_fast(respx_mock):
    async def slow(request):
        await asyncio.sleep(2)
        return httpx.Response(200, json={})

    respx_mock.get(URL).mock(side_effect=slow)
    async with httpx.AsyncClient(timeout=30) as http:
        t0 = time.monotonic()
        r = await call("s", _factory(http), timeout_s=0.1)
    assert r.status == "timeout"
    assert time.monotonic() - t0 < 1


@respx.mock(assert_all_mocked=True)
async def test_httpx_timeout_and_other_exception(respx_mock):
    respx_mock.get(URL).mock(side_effect=httpx.ReadTimeout("t"))
    async with httpx.AsyncClient() as http:
        assert (await call("s", _factory(http), timeout_s=1)).status == "timeout"
    respx_mock.get(URL).mock(side_effect=httpx.ConnectError("c"))
    async with httpx.AsyncClient() as http:
        r = await call("s", _factory(http), timeout_s=1)
    assert (r.status, r.error) == ("failed", "ConnectError")


async def test_log_has_no_secrets(caplog):
    async def boom():
        raise ValueError("Bearer topsecret")

    caplog.set_level("WARNING")
    r = await call("src", boom, timeout_s=1, tenant="acmefarm")
    assert r.error == "ValueError"
    assert "src" in caplog.text and "acmefarm" in caplog.text
    assert "topsecret" not in caplog.text


async def test_log_carries_request_id_only(caplog):
    async def boom():
        raise ValueError("x")

    caplog.set_level("WARNING")
    await call("src", boom, timeout_s=1, tenant="acmefarm", rid="rid-42")
    assert "rid=rid-42" in caplog.text


async def test_gather_with_budget():
    async def slow():
        await asyncio.sleep(5)
        return SourceResult("ok", 1)

    async def fast():
        return SourceResult("ok", 2)

    t0 = time.monotonic()
    out = await gather_with_budget(0.2, a=slow(), b=fast())
    assert time.monotonic() - t0 < 1
    assert out["b"] == SourceResult("ok", 2)
    assert out["a"] == SourceResult("timeout", None, "budget")


async def test_client_uses_source_timeout(settings_env):
    from app.config import get_settings

    async with base.client(get_settings()) as c:
        assert c.timeout.read == get_settings().source_timeout_s


async def test_budget_expiry_awaits_cancelled_tasks():
    flag = []

    async def slow():
        try:
            await asyncio.sleep(5)
        finally:
            await asyncio.sleep(0.05)  # cleanup that needs to be awaited
            flag.append("cleaned")
        return SourceResult("ok")

    out = await gather_with_budget(0.1, a=slow())
    assert out["a"].status == "timeout"
    assert flag == ["cleaned"]


async def test_outer_cancel_cleans_up_tasks():
    flag = []

    async def slow():
        try:
            await asyncio.sleep(5)
        finally:
            await asyncio.sleep(0.05)
            flag.append("cleaned")
        return SourceResult("ok")

    outer = asyncio.ensure_future(gather_with_budget(10, a=slow()))
    await asyncio.sleep(0.1)
    outer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await outer
    assert flag == ["cleaned"]


def test_lifespan_opens_and_closes_http_client(settings_env):
    from app.main import create_app

    app = create_app()
    with TestClient(app):
        http = app.state.http
        assert isinstance(http, httpx.AsyncClient)
        assert not http.is_closed
    assert http.is_closed
