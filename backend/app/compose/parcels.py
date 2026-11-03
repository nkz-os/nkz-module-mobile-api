"""Pure composition of ParcelsV1 from source results (spec 2.5). No I/O."""

from datetime import datetime

from ..ids import to_urn
from ..schemas import Light, ParcelRow, ParcelsSources, ParcelsV1
from ..sources.base import SourceResult
from ._util import _num, _str, _unwrap
from .lights import severity_to_level
from .today import _iso, _lower, _rows

_FRESHNESS = ("fresh", "aging", "stale", "none")


def _treat_by_parcel(res: SourceResult) -> dict[str, str | None]:
    """URN -> disease/alert type for active high|critical risk alerts."""
    out: dict[str, str | None] = {}
    for a in _rows(res, "alerts"):
        status = _lower(a.get("status"))
        if status is not None and status != "active":
            continue
        if _lower(a.get("severity")) not in ("high", "critical"):
            continue
        ref = _unwrap(a.get("refEntity"))
        if not isinstance(ref, str) or not ref:
            continue
        urn = to_urn(ref)
        if urn not in out:
            out[urn] = _lower(a.get("alertType")) or _str(_unwrap(a.get("disease")))
    return out


def build(*, now: datetime, parcels: SourceResult, risk_alerts: SourceResult) -> ParcelsV1:
    treat = _treat_by_parcel(risk_alerts)
    rows: list[ParcelRow] = []
    for r in _rows(parcels, "parcels"):
        pid = _str(r.get("parcelId"))
        if not pid:
            continue
        urn = to_urn(pid)
        level = severity_to_level(_str(r.get("overallSeverity")))
        overall = Light(level=level, messageKey=f"state.overall.{level}", params={})
        if urn in treat:
            overall = Light(level="bad", messageKey="state.risks.treat",
                            params={"disease": treat[urn]})
        fresh = r.get("freshness")
        rows.append(ParcelRow(
            parcelId=urn, parcelName=_str(r.get("parcelName")) or pid,
            areaHa=_num(r.get("areaHa")), cropName=_str(r.get("cropName")),
            stage=_str(r.get("phenologyStage")), overall=overall,
            assessedAt=_str(r.get("assessedAt")),
            freshness=fresh if fresh in _FRESHNESS else "none"))
    return ParcelsV1(generatedAt=_iso(now), sources=ParcelsSources(cropHealth=parcels.status),
                     parcels=rows)
