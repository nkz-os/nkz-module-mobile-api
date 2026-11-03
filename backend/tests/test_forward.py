from types import SimpleNamespace

from starlette.requests import Request

from app.forward import Identity, from_request


def _req(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "method": "GET", "path": "/"})


def test_copies_exactly_six_headers_and_drops_others():
    req = _req({
        "authorization": "Bearer t", "X-Tenant-ID": "acmefarm", "X-User-ID": "user-1",
        "X-User-Roles": "Farmer", "X-Auth-Signature": "sig:1",
        "X-Request-ID": "rid-1", "Cookie": "nkz_token=secret", "Host": "example.invalid", "X-Other": "x",
    })
    ident = from_request(req, SimpleNamespace(tenant_id="acmefarm"))
    assert ident.tenant_id == "acmefarm"
    assert ident.headers == {
        "Authorization": "Bearer t", "X-Tenant-ID": "acmefarm", "X-User-ID": "user-1",
        "X-User-Roles": "Farmer", "X-Auth-Signature": "sig:1", "X-Request-ID": "rid-1",
    }
    assert ident.request_id == "rid-1"


def test_missing_headers_are_omitted():
    ident = from_request(_req({"X-Tenant-ID": "acmefarm"}), SimpleNamespace(tenant_id="acmefarm"))
    assert ident.headers == {"X-Tenant-ID": "acmefarm"}


def test_repr_and_str_hide_values():
    ident = Identity(headers={"Authorization": "Bearer topsecret", "X-Tenant-ID": "acmefarm"},
                     tenant_id="acmefarm")
    for text in (repr(ident), str(ident)):
        assert "topsecret" not in text
        assert text == "Identity(tenant=acmefarm, headers=<2 keys>)"


def test_request_id_defaults_to_empty():
    ident = from_request(_req({"X-Tenant-ID": "acmefarm"}), SimpleNamespace(tenant_id="acmefarm"))
    assert ident.request_id == ""
