"""Deterministic traffic-light mapping (spec 2.2). Pure functions over plain dicts."""

from typing import Any, Literal

from app.schemas import Light

Level = Literal["ok", "warn", "bad", "unknown"]

_RANK: dict[str, int] = {"ok": 0, "unknown": 1, "warn": 2, "bad": 3}
_UNKNOWN_KEY = "state.unknown"


def _unknown() -> Light:
    return Light(level="unknown", messageKey=_UNKNOWN_KEY)


def _s(value: Any) -> str:
    """Lower-cased string, '' when absent."""
    return str(value).strip().lower() if value is not None else ""


def _sub(assessment: dict, key: str, field: str) -> str:
    block = assessment.get(key)
    return _s(block.get(field)) if isinstance(block, dict) else ""


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def water(assessment: dict | None) -> Light:
    if not assessment:
        return _unknown()
    action = _s(assessment.get("recommendedAction"))
    stress = _sub(assessment, "soilWaterBalance", "stressLevel")
    if action == "irrigate_immediate" or stress == "critical":
        return Light(level="bad", messageKey="state.water.irrigate_now")
    if action == "irrigate_scheduled" or stress in ("high", "moderate"):
        return Light(level="warn", messageKey="state.water.irrigate_soon")
    if _sub(assessment, "waterloggingRisk", "riskLevel") in ("high", "critical"):
        return Light(level="warn", messageKey="state.water.too_wet")
    return Light(level="ok", messageKey="state.water.ok")


def plant(assessment: dict | None) -> Light:
    if not assessment:
        return _unknown()
    index = _num(assessment.get("compositeStressIndex"))
    thermal = _s(assessment.get("thermalSeverity"))
    if index is not None and index >= 60:
        return Light(
            level="bad",
            messageKey="state.plant.stressed",
            params={"stressor": assessment.get("dominantStressor")},
        )
    if thermal in ("high", "critical"):
        frost = _num(assessment.get("frostHours"))
        key = "state.plant.frost" if frost is not None and frost > 0 else "state.plant.heat"
        return Light(level="bad", messageKey=key)
    if _s(assessment.get("vigorCondition")) in ("below_expected", "anomalous_senescence"):
        return Light(level="warn", messageKey="state.plant.vigor_low")
    return Light(level="ok", messageKey="state.plant.ok")


def _frost_is_bad(alert: dict) -> bool:
    """Frost is urgent only when critical, or tonight's (or the night in progress)
    minimum is below 0 C. Missing or malformed evaluation data is never urgent."""
    if _s(alert.get("severity")) == "critical":
        return True
    data = alert.get("evaluationData")
    if isinstance(data, dict) and isinstance(data.get("value"), dict):
        data = data["value"]
    if not isinstance(data, dict):
        return False
    lead, tmin = _num(data.get("text_lead")), _num(data.get("text_tmin_c"))
    return lead is not None and tmin is not None and lead <= 1 and tmin < 0


def risks(
    diseases: list | None,
    risk_alerts: list | None,
    sources_ok: bool,
) -> Light:
    """diseases: crop-health `risks[]` (risk_level, disease); risk_alerts: already
    filtered to the parcel (severity lower-case, optional evaluationData). Frost
    alerts follow `_frost_is_bad`; a frost light never carries the raw alert code."""
    bad: Light | None = None
    warn: Light | None = None
    frost_bad: Light | None = None
    frost_warn: Light | None = None

    def disease_params(item: dict) -> dict[str, Any]:
        name = item.get("disease") or item.get("alertType")
        return {"disease": name} if name else {}

    for d in diseases if isinstance(diseases, list) else []:
        if not isinstance(d, dict):
            continue
        level = _s(d.get("risk_level"))
        if level in ("high", "critical") and bad is None:
            bad = Light(level="bad", messageKey="state.risks.treat", params=disease_params(d))
        elif level == "medium" and warn is None:
            warn = Light(level="warn", messageKey="state.risks.watch", params=disease_params(d))
    for a in risk_alerts if isinstance(risk_alerts, list) else []:
        if not isinstance(a, dict):
            continue
        if _s(a.get("alertType")) == "frost":
            if _frost_is_bad(a):
                frost_bad = frost_bad or Light(level="bad", messageKey="state.risks.frost_act")
            else:
                frost_warn = frost_warn or Light(level="warn", messageKey="state.risks.frost_watch")
            continue
        level = _s(a.get("severity"))
        if level in ("high", "critical") and bad is None:
            bad = Light(level="bad", messageKey="state.risks.treat", params=disease_params(a))
        elif level == "medium" and warn is None:
            warn = Light(level="warn", messageKey="state.risks.watch", params=disease_params(a))

    if bad is not None:
        return bad
    if frost_bad is not None:
        return frost_bad
    if frost_warn is not None:
        return frost_warn
    if warn is not None:
        return warn
    if not sources_ok:
        return _unknown()
    return Light(level="ok", messageKey="state.risks.ok")


def overall(*items: Light) -> Light:
    """Worst wins (bad > warn > unknown > ok); ties keep the first given."""
    if not items:
        return _unknown()
    worst = items[0]
    for item in items[1:]:
        if _RANK[item.level] > _RANK[worst.level]:
            worst = item
    return Light(level=worst.level, messageKey=worst.messageKey, params=dict(worst.params))


def severity_to_level(overall_severity: str | None) -> Level:
    sev = _s(overall_severity)
    if sev == "low":
        return "ok"
    if sev == "medium":
        return "warn"
    if sev in ("high", "critical"):
        return "bad"
    return "unknown"
