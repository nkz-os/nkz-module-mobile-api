from datetime import datetime, timezone

from app.compose import parcels as compose
from app.sources.base import SourceResult

NOW = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
P = "urn:ngsi-ld:AgriParcel:"


def _ch(*rows):
    return SourceResult("ok", data={"parcels": list(rows)})


def _risk(*alerts):
    return SourceResult("ok", data={"alerts": list(alerts)})


def _row(pid="p1", sev="LOW", **kw):
    return {"parcelId": pid, "parcelName": "Norte", "overallSeverity": sev, **kw}


def _alert(ref, sev="high", status="active", atype="mildew"):
    return {"id": "a", "severity": {"type": "Property", "value": sev},
            "status": {"type": "Property", "value": status},
            "alertType": {"type": "Property", "value": atype},
            "refEntity": {"type": "Relationship", "object": ref}}


def test_severity_mapping_and_fields():
    out = compose.build(now=NOW, risk_alerts=_risk(), parcels=_ch(
        _row("p1", "LOW", cropName="Wheat", phenologyStage="tillering", areaHa=2.5,
             assessedAt="2026-11-02T10:00:00Z", freshness="fresh"),
        _row("p2", "MEDIUM"), _row("p3", "HIGH"), _row("p4", "CRITICAL"), _row("p5", None)))
    assert out.version == 1 and out.generatedAt == "2026-11-03T08:00:00Z"
    assert out.sources.cropHealth == "ok"
    levels = [r.overall.level for r in out.parcels]
    assert levels == ["ok", "warn", "bad", "bad", "unknown"]
    r = out.parcels[0]
    assert r.parcelId == P + "p1" and r.parcelName == "Norte"
    assert (r.cropName, r.stage, r.areaHa, r.freshness) == ("Wheat", "tillering", 2.5, "fresh")
    assert r.assessedAt == "2026-11-02T10:00:00Z"
    assert r.overall.messageKey == "state.overall.ok"
    assert out.parcels[4].overall.messageKey == "state.overall.unknown"
    assert out.parcels[4].freshness == "none" and out.parcels[4].areaHa is None


def test_risk_raises_to_bad_only_for_high_critical_active_same_parcel():
    out = compose.build(now=NOW, parcels=_ch(_row("p1"), _row("p2"), _row("p3")), risk_alerts=_risk(
        _alert(P + "p1", "critical"), _alert("p2", "medium"), _alert(P + "p3", "high", status="closed")))
    p1, p2, p3 = out.parcels
    assert p1.overall.level == "bad" and p1.overall.messageKey == "state.risks.treat"
    assert p1.overall.params == {"disease": "mildew"}
    assert p2.overall.level == "ok" and p3.overall.level == "ok"


def test_risk_alert_short_ref_normalized():
    out = compose.build(now=NOW, parcels=_ch(_row("p1")), risk_alerts=_risk(_alert("p1", "high")))
    assert out.parcels[0].overall.level == "bad"


def test_failed_sources_and_empty():
    out = compose.build(now=NOW, parcels=SourceResult("failed"), risk_alerts=SourceResult("failed"))
    assert out.parcels == [] and out.sources.cropHealth == "failed"
    out = compose.build(now=NOW, parcels=SourceResult("empty"), risk_alerts=SourceResult("empty"))
    assert out.parcels == [] and out.sources.cropHealth == "empty"


def test_rows_without_id_skipped_and_bad_freshness_none():
    out = compose.build(now=NOW, risk_alerts=_risk(), parcels=_ch(
        {"parcelName": "x"}, _row("p1", freshness="weird")))
    assert [r.parcelId for r in out.parcels] == [P + "p1"]
    assert out.parcels[0].freshness == "none"


def test_sources_include_risk_status():
    out = compose.build(now=NOW, parcels=_ch(_row()), risk_alerts=SourceResult("failed"))
    assert out.sources.model_dump() == {"cropHealth": "ok", "risk": "failed"}
