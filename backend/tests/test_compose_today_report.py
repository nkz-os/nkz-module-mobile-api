from datetime import datetime, timezone

from app.compose import today
from app.sources.base import SourceResult

NOW = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
REPORT = {"reportId": "r-1", "weekStart": "2026-11-02", "status": "complete",
          "generatedAt": "2026-11-02T06:00:00Z", "plain": {"title": "Weekly", "body": "All calm"}}


def _ok(key, rows):
    return SourceResult("ok", data={key: rows})


def _parcel(i):
    return {"parcelId": f"p{i}", "parcelName": "N", "hasData": True, "cropStatus": "active",
            "nextJob": {"kind": "pending_assessment", "when": None, "detail": {}}}


def build(report, parcels=()):
    return today.build(now=NOW, lang="es", parcels=_ok("parcels", list(parcels)),
                       risk_alerts=_ok("alerts", []), wx_alerts=_ok("alerts", []), report=report)


def test_card_last():
    out = build(SourceResult("ok", data=REPORT), [_parcel(1), _parcel(2)])
    kinds = [c.kind for c in out.cards]
    assert kinds == ["info", "info", "weekly_report"]
    c = out.cards[-1]
    assert c.urgency == "silent" and c.parcelId is None and c.parcelName is None
    assert c.messageKey == "card.weekly_report" and c.id == "weekly_report:r-1"
    assert c.plain.title == "Weekly" and c.plain.body == "All calm"
    assert c.action.kind == "none" and c.action.params == {}
    assert out.sources.notifications == "ok"


def test_card_survives_cap():
    out = build(SourceResult("ok", data=REPORT), [_parcel(i) for i in range(60)])
    assert len(out.cards) == 50 and out.cards[-1].kind == "weekly_report"


def test_version_still_1():
    assert build(SourceResult("empty")).version == 1


def test_no_card_when_not_ok():
    for st in ("empty", "failed", "timeout"):
        out = build(SourceResult(st))
        assert out.cards == [] and out.sources.notifications == st


def test_malformed_is_failed_no_card():
    for bad in (None, [], {}, {"reportId": "r"}, {"reportId": "r", "plain": {"body": "b"}},
                {"reportId": "r", "plain": {"title": "t"}}, {"plain": {"title": "t", "body": "b"}},
                {"reportId": "r", "plain": "x"}):
        out = build(SourceResult("ok", data=bad))
        assert out.cards == [] and out.sources.notifications == "failed", bad
