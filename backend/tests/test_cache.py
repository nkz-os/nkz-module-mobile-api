from app.cache import TTLCache


def test_ttl_and_tenant_isolation():
    t = [0.0]
    c = TTLCache(60, clock=lambda: t[0])
    c.set("a", "k", 1)
    assert c.get("a", "k") == 1 and c.get("b", "k") is None
    t[0] = 59.9
    assert c.get("a", "k") == 1
    t[0] = 60.0
    assert c.get("a", "k") is None
