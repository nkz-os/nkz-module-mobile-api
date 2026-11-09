"""Pure composition of ParcelsV1 from source results (spec 2.5). No I/O."""

from datetime import datetime

from ..ids import to_urn
from ..schemas import Light, ParcelRow, ParcelsSources, ParcelsV1
from ..sources.base import SourceResult
from ._util import _lower, _num, _str, _unwrap, alert_is_active, alert_ref_urn
from .lights import overall as lights_overall
from .lights import risks, severity_to_level
from .today import _iso, _rows

_FRESHNESS = ("fresh", "aging", "stale", "none")


def _alerts_by_parcel(res: SourceResult) -> dict[str, list[dict]]:
    """URN -> active risk alerts, in the shape `lights.risks` reads."""
    out: dict[str, list[dict]] = {}
    for a in _rows(res, "alerts"):
        if not alert_is_active(a):
            continue
        urn = alert_ref_urn(a)
        if urn is None:
            continue
        out.setdefault(urn, []).append({
            "severity": _unwrap(a.get("severity")),
            "alertType": _lower(a.get("alertType")) or _str(_unwrap(a.get("disease"))),
            "evaluationData": _unwrap(a.get("evaluationData")),
        })
    return out


def build(*, now: datetime, parcels: SourceResult, risk_alerts: SourceResult) -> ParcelsV1:
    alerts = _alerts_by_parcel(risk_alerts)
    rows: list[ParcelRow] = []
    for r in _rows(parcels, "parcels"):
        pid = _str(r.get("parcelId"))
        if not pid:
            continue
        urn = to_urn(pid)
        level = severity_to_level(_str(r.get("overallSeverity")))
        overall = Light(level=level, messageKey=f"state.overall.{level}", params={})
        # Only high|critical non-frost alerts and frost alerts move the list light;
        # medium non-frost alerts never did. Frost may be amber, so it keeps a worse
        # crop-health light instead of replacing it.
        risk = risks(None, alerts.get(urn), True)
        if risk.level == "bad":
            overall = risk
        elif risk.messageKey == "state.risks.frost_watch":
            overall = lights_overall(overall, risk)
        fresh = r.get("freshness")
        rows.append(ParcelRow(
            parcelId=urn, parcelName=_str(r.get("parcelName")) or pid,
            areaHa=_num(r.get("areaHa")), cropName=_str(r.get("cropName")),
            stage=_str(r.get("phenologyStage")), overall=overall,
            assessedAt=_str(r.get("assessedAt")),
            freshness=fresh if fresh in _FRESHNESS else "none"))
    return ParcelsV1(generatedAt=_iso(now), sources=ParcelsSources(cropHealth=parcels.status, risk=risk_alerts.status),
                     parcels=rows)
