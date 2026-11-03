from datetime import datetime, timezone

from app.compose import today
from app.sources.base import SourceResult

NOW = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
P = "urn:ngsi-ld:AgriParcel:"


def ok(data):
    return SourceResult("ok", data=data)


def row(pid="p1", **kw):
    base = {"parcelId": pid, "parcelName": "Norte", "hasData": True, "cropStatus": "active",
            "nextJob": None}
    base.update(kw)
    return base


def risk(aid="a1", sev="high", cat="disease", atype="Mildew", ref="p1", **kw):
    a = {"id": aid, "category": {"type": "Property", "value": cat},
         "alertType": {"type": "Property", "value": atype},
         "severity": {"type": "Property", "value": sev},
         "refEntity": {"type": "Relationship", "object": P + ref},
         "refEntityName": {"type": "Property", "value": "Norte"}}
    a.update(kw)
    return a


def wx(i, sev, vf="2026-11-04T00:00:00Z"):
    return {"id": f"w{i}", "severity": sev, "description": f"d{i}", "validFrom": vf,
            "validTo": "2026-11-05T00:00:00Z"}


def build(parcels=None, risks=None, wxs=None, lang="es"):
    mk = lambda k, v: v if isinstance(v, SourceResult) else ok({k: v or []})
    return today.build(now=NOW, lang=lang, parcels=mk("parcels", parcels),
                       risk_alerts=mk("alerts", risks), wx_alerts=mk("alerts", wxs))


def test_risk_alert_card_vibrates_for_high_disease():
    out = build(risks=[risk()])
    c = out.cards[0]
    assert c.id == "a1" and c.kind == "alert" and c.urgency == "vibrate"
    assert c.parcelId == P + "p1" and c.parcelName == "Norte"
    assert c.messageKey == "card.alert.mildew"
    assert c.params == {"severity": "high", "category": "disease"}
    assert c.action.kind == "open_parcel" and c.action.params == {"parcelId": P + "p1"}
    assert c.at == "2026-11-03T08:00:00Z" and c.plain is None


def test_risk_alert_silent_when_not_disease_or_not_high():
    out = build(risks=[risk("a1", "medium", "disease"), risk("a2", "critical", "crop"),
                       risk("a3", "high", "crop")])
    assert [c.urgency for c in out.cards] == ["silent"] * 3


def test_risk_plain_and_explicit_urgency_and_plain_values():
    a = risk(plain={"es": {"title": "T", "body": "B"}}, urgency="silent")
    a2 = risk("a2", plain={"lang": {"es": {"title": "T2", "body": "B2"}}})
    a3 = {"id": "a3", "category": "disease", "alertType": "X", "severity": "critical",
          "refEntity": "p1", "observedAt": "2026-11-02T10:00:00Z"}
    out = build(risks=[a, a2, a3])
    by = {c.id: c for c in out.cards}
    assert by["a1"].plain.title == "T" and by["a1"].urgency == "silent"
    assert by["a2"].plain.body == "B2"
    assert by["a3"].plain is None and by["a3"].urgency == "vibrate"
    assert by["a3"].at == "2026-11-02T10:00:00Z" and by["a3"].parcelId == P + "p1"
    assert by["a3"].parcelName is None


def test_plain_missing_lang_is_none():
    out = build(risks=[risk(plain={"en": {"title": "T", "body": "B"}})])
    assert out.cards[0].plain is None


def test_weather_alerts_filter_cap_and_urgency():
    ws = [wx(1, "minor")] + [wx(i, "moderate", f"2026-11-0{i}T00:00:00Z") for i in range(2, 6)] \
        + [wx(6, "severe"), wx(7, "severe", "2026-11-01T00:00:00Z"), wx(8, "moderate", "2026-11-09T00:00:00Z")]
    out = build(wxs=ws)
    ids = [c.id for c in out.cards]
    assert len(ids) == 5 and "w1" not in ids
    assert ids[:2] == ["w6", "w7"]  # severe first, then validFrom desc
    c = out.cards[0]
    assert c.parcelId is None and c.messageKey == "card.alert.weather"
    assert c.params == {"severity": "severe", "headline": "d6"} and c.urgency == "vibrate"
    assert out.cards[2].urgency == "silent"
    assert c.at == "2026-11-04T00:00:00Z"


def test_job_cards_and_actions():
    rows = [
        row("p1", nextJob={"kind": "irrigate", "when": "today", "detail": {"mm": 12}}),
        row("p2", nextJob={"kind": "harvest", "when": "tomorrow", "detail": {}}),
        row("p3", nextJob={"kind": "scout", "when": "today", "detail": {}}),
    ]
    out = build(parcels=rows)
    by = {c.id: c for c in out.cards}
    j1 = by["job:" + P + "p1:irrigate"]
    assert j1.kind == "job" and j1.urgency == "vibrate" and j1.messageKey == "card.job.irrigate"
    assert j1.params == {"mm": 12, "when": "today"}
    assert j1.action.kind == "record_operation"
    assert j1.action.params == {"parcelId": P + "p1", "kind": "irrigate"}
    j2 = by["job:" + P + "p2:harvest"]
    assert j2.urgency == "silent" and j2.action.kind == "record_operation"
    j3 = by["job:" + P + "p3:scout"]
    assert j3.urgency == "silent" and j3.action.kind == "open_parcel"
    assert j3.parcelName == "Norte"


def test_info_cards_for_pending_and_none_until():
    rows = [row("p1", nextJob={"kind": "pending_assessment", "when": "today", "detail": {}}),
            row("p2", nextJob={"kind": "none_until", "when": "later", "detail": {}})]
    out = build(parcels=rows)
    assert [c.kind for c in out.cards] == ["info", "info"]
    assert all(c.urgency == "silent" and c.action.kind == "open_parcel" for c in out.cards)
    assert out.cards[0].id == f"info:{P}p1:pending_assessment"
    assert out.summary.jobsToday == 0


def test_none_row_no_card_but_surprise_kept():
    rows = [row("p1", cropStatus="none", nextJob=None),
            row("p2", cropStatus="none", nextJob=None,
                surprise={"code": "frost_risk", "detail": {"tminC": -2}})]
    out = build(parcels=rows)
    assert [c.id for c in out.cards] == [f"surprise:{P}p2:frost_risk"]
    c = out.cards[0]
    assert c.kind == "surprise" and c.messageKey == "card.surprise.frost_risk"
    assert c.params == {"tminC": -2} and c.urgency == "silent"
    assert out.summary.surprises == 1


def test_ordering_and_summary():
    rows = [
        row("p1", nextJob={"kind": "scout", "when": "tomorrow", "detail": {}}),
        row("p2", nextJob={"kind": "sow", "when": "today", "detail": {}},
            surprise={"code": "s", "detail": {}}),
        row("p3", nextJob={"kind": "none_until", "when": "later", "detail": {}}),
        row("p4", hasData=False, cropStatus="none"),
        {"parcelId": "p5", "parcelName": "X"},  # missing hasData
    ]
    out = build(parcels=rows, risks=[risk("a1", "medium", "crop"), risk("a2", "critical", "pest")],
                wxs=[wx(1, "moderate")])
    ids = [c.id for c in out.cards]
    assert ids == ["a2", "a1", "w1", f"job:{P}p2:sow", f"job:{P}p1:scout",
                   f"surprise:{P}p2:s", f"info:{P}p3:none_until"]
    assert out.summary.model_dump() == {"alerts": 3, "jobsToday": 1, "surprises": 1, "noData": 2}


def test_alert_severity_order_within_non_vibrate():
    out = build(risks=[risk("a1", "low", "crop"), risk("a2", "medium", "crop"),
                       risk("a3", "high", "crop")], wxs=[wx(1, "moderate")])
    assert [c.id for c in out.cards] == ["a3", "a2", "a1", "w1"]


def test_cap_50_after_ordering():
    rows = [row(f"p{i}", nextJob={"kind": "scout", "when": "later", "detail": {}}) for i in range(60)]
    out = build(parcels=rows, risks=[risk("a1")])
    assert len(out.cards) == 50 and out.cards[0].id == "a1"


def test_sources_and_failed_inputs():
    out = today.build(now=NOW, lang="es", parcels=SourceResult("empty"),
                      risk_alerts=SourceResult("failed", error="http_500"),
                      wx_alerts=SourceResult("timeout"))
    assert out.cards == []
    assert out.sources.model_dump() == {"cropHealth": "empty", "risk": "failed", "weather": "timeout"}
    assert out.generatedAt == "2026-11-03T08:00:00Z" and out.version == 1


def test_resolved_risk_alert_skipped():
    out = build(risks=[risk("a1", status={"type": "Property", "value": "resolved"})])
    assert out.cards == []
