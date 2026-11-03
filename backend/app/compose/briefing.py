"""Pure composition of BriefingV1 from source results (spec 2.3). No I/O."""

from datetime import date, datetime, timezone
from typing import Any

from ..schemas import (
    BriefingSources, BriefingV1, Campaign, Crop, Freshness, LabAnalysis, LastOperation,
    NextJob, Operation, PlannedCrop, Soil, SoilMoisture, State, Surprise, Topsoil,
    Weather, WeatherAlert, WeatherDay, WeatherNow, WeatherSemaphores, YieldForecast,
    YieldValue,
)
from ..sources.base import SourceResult
from ..ids import to_urn
from . import lights, wmo

_ORDER = {"ok": 0, "empty": 1, "failed": 2, "timeout": 3}
_SEMAPHORES = {"optimal", "satisfied", "caution", "deficit", "not_suitable",
               "too_wet", "too_dry", "alert", "unknown"}
_MOISTURE = {"none", "moderate", "high", "critical"}
_FRESHNESS = {"fresh", "aging", "stale", "none"}


def _worst(*results: SourceResult) -> str:
    return max((r.status for r in results), key=lambda s: _ORDER[s])


def _data(res: SourceResult) -> dict:
    return res.data if res.status == "ok" and isinstance(res.data, dict) else {}


def _ok(res: SourceResult) -> bool:
    return res.status == "ok" and isinstance(res.data, dict)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _str(v: Any) -> str | None:
    return v if isinstance(v, str) and v else None


def _unwrap(v: Any) -> Any:
    """NGSI-LD Property/Relationship -> bare value; bare values pass through."""
    if isinstance(v, dict):
        if "value" in v:
            return v["value"]
        if "object" in v:
            return v["object"]
    return v


def _days_since(start: str | None, now: datetime) -> int | None:
    if not start:
        return None
    try:
        return max(0, (now.date() - date.fromisoformat(start[:10])).days)
    except ValueError:
        return None


# --- sections ---------------------------------------------------------------

def _planned(latest: SourceResult, lang: str) -> PlannedCrop | None:
    p = _data(latest).get("plannedCrop")
    if not isinstance(p, dict):
        return None
    species, sowing = _str(p.get("species")), _str(p.get("sowingDate"))
    names = p.get("names") if isinstance(p.get("names"), dict) else {}
    name = _str(names.get(lang)) or _str(names.get("es")) or species
    if not (species and sowing and name):
        return None
    return PlannedCrop(species=species, name=name, sowingDate=sowing)


def _assessment(latest: SourceResult) -> dict | None:
    rows = _data(latest).get("assessments")
    return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None


def _crop(crop: SourceResult, latest: SourceResult, lang: str, now: datetime) -> Crop:
    planned = _planned(latest, lang)
    if not _ok(crop):
        return Crop(status="unknown", variety=None, sowingDate=None, provenance=None,
                    daysSinceSowing=None, plannedCrop=planned)
    timeline = crop.data.get("timeline") or {}
    current = timeline.get("current")
    if not isinstance(current, dict):
        return Crop(status="none", variety=None, sowingDate=None, provenance=None,
                    daysSinceSowing=None, plannedCrop=planned)
    start = current.get("start") if isinstance(current.get("start"), dict) else {}
    prov = start.get("provenance")
    prov = prov if prov in ("actual", "declared", "planned") else None
    sowing = _str(start.get("date"))
    active = prov in ("actual", "declared")
    assessment = _assessment(latest) or {}
    return Crop(
        status="active" if active else "none",
        species=_str(current.get("species")),
        name=_str(assessment.get("cropName")),
        variety=_str(crop.data.get("variety")),
        sowingDate=sowing,
        provenance=prov,
        daysSinceSowing=_days_since(sowing, now) if active else None,
        plannedCrop=planned,
    )


def _campaign(phenology: SourceResult) -> Campaign | None:
    d = _data(phenology)
    stage = _str(d.get("currentStage"))
    if not stage:
        return None
    gdd = d.get("gdd") if isinstance(d.get("gdd"), dict) else {}
    dev = d.get("deviation")
    dev = dev if isinstance(dev, str) or _num(dev) is not None else None
    return Campaign(stage=stage, progressPct=_num(d.get("stageProgressPct")),
                    deviation=dev if isinstance(dev, str) else _num(dev),
                    gddAccumulated=_num(gdd.get("accumulated")),
                    dataFidelity=_str(d.get("dataFidelity")) or "unavailable")


def _weather(agro: SourceResult, forecast3: SourceResult, wx_alerts: SourceResult) -> Weather | None:
    if not (_ok(agro) or _ok(forecast3) or _ok(wx_alerts)):
        return None
    a = _data(agro)
    w = a.get("weather")
    now = None
    if isinstance(w, dict):
        now = WeatherNow(observedAt=_str(w.get("observed_at")), tempC=_num(w.get("temperature")),
                         humidityPct=_num(w.get("humidity")), windMs=_num(w.get("wind_speed")),
                         precipMm=_num(w.get("precipitation")))
    sem = a.get("semaphores") if isinstance(a.get("semaphores"), dict) else {}

    def level(k: str) -> str:
        v = sem.get(k)
        return v if isinstance(v, str) and v in _SEMAPHORES else "unknown"

    days: list[WeatherDay] = []
    rows = _data(forecast3).get("forecast")
    for r in (rows if isinstance(rows, list) else [])[:3]:
        if not isinstance(r, dict):
            continue
        code = r.get("weather_code")
        vals = (_str(r.get("date")), _num(r.get("temp_min")), _num(r.get("temp_max")),
                _num(r.get("precip_mm")), _num(r.get("precip_probability")))
        if any(v is None for v in vals) or isinstance(code, bool) or not isinstance(code, int):
            continue  # schema requires every value: drop the row, never invent
        days.append(WeatherDay(date=vals[0], tminC=vals[1], tmaxC=vals[2], precipMm=vals[3],
                               precipProbPct=vals[4], code=code, codeKey=wmo.code_key(code)))

    alerts: list[WeatherAlert] = []
    arows = _data(wx_alerts).get("alerts")
    for r in (arows if isinstance(arows, list) else []):
        if not isinstance(r, dict):
            continue
        sev = _str(r.get("severity"))
        head = _str(r.get("headline")) or _str(r.get("description"))
        vf, vt = _str(r.get("validFrom")), _str(r.get("validTo"))
        if sev and head and vf and vt:
            alerts.append(WeatherAlert(severity=sev, headline=head, validFrom=vf, validTo=vt))

    return Weather(now=now, semaphores=WeatherSemaphores(
        spraying=level("spraying"), workability=level("workability"), irrigation=level("irrigation")),
        days=days, alerts=alerts)


def _topsoil(soil_summary: SourceResult) -> Topsoil | None:
    hz = _data(soil_summary).get("horizons")
    h = hz[0] if isinstance(hz, list) and hz and isinstance(hz[0], dict) else None
    if h is None:
        return None
    oc = _num(h.get("organicCarbon"))
    vals = [_num(h.get(k)) for k in ("depthFrom", "depthTo", "sand", "clay", "silt")]
    if oc is None or any(v is None for v in vals):
        return None
    return Topsoil(depthFrom=vals[0], depthTo=vals[1], sandPct=vals[2], clayPct=vals[3],
                   siltPct=vals[4], organicMatterPct=round(oc * 1.724, 3))


def _texture(soil_summary: SourceResult, latest: SourceResult) -> str | None:
    t = _str(_data(soil_summary).get("usdaTextureClass"))
    if t:
        return t
    for holder in (_assessment(latest) or {}, _data(latest)):
        props = holder.get("soilProperties")
        if isinstance(props, dict) and _str(props.get("usdaTextureClass")):
            return props["usdaTextureClass"]
    return None


def _moisture(latest: SourceResult) -> SoilMoisture:
    swb = (_assessment(latest) or {}).get("soilWaterBalance")
    if not isinstance(swb, dict):
        return SoilMoisture(level="unknown", ratio=None)
    lvl = str(swb.get("stressLevel") or "").lower()
    return SoilMoisture(level=lvl if lvl in _MOISTURE else "unknown", ratio=_num(swb.get("swRatio")))


def _ops(ops: SourceResult) -> list[Operation]:
    rows = _data(ops).get("operations")
    out: list[Operation] = []
    for r in (rows if isinstance(rows, list) else []):
        if not isinstance(r, dict):
            continue
        when = _str(r.get("endedAt")) or _str(r.get("startedAt"))
        oid, typ = _str(r.get("id")), _str(r.get("operationType"))
        if oid and typ and when:
            out.append(Operation(id=oid, type=typ, date=when, status=_str(r.get("status")) or "unknown"))
    out.sort(key=lambda o: o.date, reverse=True)
    return out


def _soil(soil_summary: SourceResult, labs: SourceResult, latest: SourceResult,
          operations: list[Operation]) -> Soil | None:
    topsoil = _topsoil(soil_summary)
    texture = _texture(soil_summary, latest)
    moisture = _moisture(latest)
    lab = None
    arows = _data(labs).get("analyses")
    if isinstance(arows, list) and arows and isinstance(arows[0], dict):
        d, ref = _str(arows[0].get("samplingDate")), _str(arows[0].get("laboratoryReference"))
        if d and ref:
            lab = LabAnalysis(date=d, reference=ref)
    last = None
    if operations:
        o = operations[0]
        last = LastOperation(type=o.type, date=o.date, status=o.status)
    if topsoil is None and texture is None and lab is None and last is None \
            and moisture.level == "unknown":
        return None
    return Soil(textureClass=texture, topsoil=topsoil, moisture=moisture,
                lastLabAnalysis=lab, lastOperation=last)


def _risk_alerts_for(risk_alerts: SourceResult, parcel_urn: str) -> list[dict]:
    rows = _data(risk_alerts).get("alerts")
    out: list[dict] = []
    for a in (rows if isinstance(rows, list) else []):
        if not isinstance(a, dict):
            continue
        ref = _unwrap(a.get("refEntity"))
        if not isinstance(ref, str) or to_urn(ref) != parcel_urn:
            continue
        status = _unwrap(a.get("status"))
        if status is not None and str(status).lower() != "active":
            continue
        out.append({"severity": _unwrap(a.get("severity")), "alertType": _unwrap(a.get("alertType"))})
    return out


def _state(latest: SourceResult, diseases: SourceResult, risk_alerts: SourceResult,
           parcel_urn: str) -> State | None:
    assessment = _assessment(latest)
    if assessment is None:
        return None
    risk_ok = diseases.status in ("ok", "empty") and risk_alerts.status in ("ok", "empty")
    water = lights.water(assessment)
    plant = lights.plant(assessment)
    risk = lights.risks(_data(diseases).get("risks"), _risk_alerts_for(risk_alerts, parcel_urn), risk_ok)
    fresh = _data(latest).get("freshness")
    return State(water=water, plant=plant, risks=risk, overall=lights.overall(water, plant, risk),
                 assessedAt=_str(assessment.get("assessedAt")),
                 freshness=fresh if fresh in _FRESHNESS else "none")


def _forecast(yield_fc: SourceResult) -> YieldForecast | None:
    d = _data(yield_fc)
    est = d.get("estimates")
    if d.get("status") != "done" or not isinstance(est, list) or not est or not isinstance(est[0], dict):
        return None
    e = est[0]
    value, computed = _num(e.get("value")), _str(d.get("computed_at"))
    if value is None or computed is None:
        return None
    return YieldForecast(
        yield_=YieldValue(value=value, unit=_str(e.get("unit")) or "t/ha",
                          low=_num(e.get("low")), high=_num(e.get("high"))),
        harvestDate=_str(d.get("harvestDate")) or _str(e.get("harvestDate")),
        computedAt=computed)


def _next_job(latest: SourceResult) -> NextJob | None:
    j = _data(latest).get("nextJob")
    if isinstance(j, dict) and _str(j.get("kind")) and _str(j.get("when")):
        return NextJob(kind=j["kind"], when=j["when"],
                       detail=j["detail"] if isinstance(j.get("detail"), dict) else {})
    return None


def _surprise(latest: SourceResult) -> Surprise | None:
    s = _data(latest).get("surprise")
    if isinstance(s, dict) and _str(s.get("code")):
        return Surprise(code=s["code"], detail=s["detail"] if isinstance(s.get("detail"), dict) else {})
    return None


def build(*, parcel_urn: str, parcel_name: str | None, lang: str, now: datetime,
          crop: SourceResult, latest: SourceResult, diseases: SourceResult,
          phenology: SourceResult, agro: SourceResult, forecast3: SourceResult,
          wx_alerts: SourceResult, soil_summary: SourceResult, labs: SourceResult,
          ops: SourceResult, risk_alerts: SourceResult, yield_fc: SourceResult) -> BriefingV1:
    operations = _ops(ops)
    # BriefingV1.parcelName is a required str: fall back to names sources carry, else "".
    name = (parcel_name or _str((_assessment(latest) or {}).get("parcelName"))
            or _str(_data(agro).get("parcel_name")) or "")
    return BriefingV1(
        parcelId=parcel_urn,
        parcelName=name,
        generatedAt=now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        lang=lang,
        sources=BriefingSources(
            cropHealth=_worst(crop, latest, diseases, phenology),
            weather=_worst(agro, forecast3, wx_alerts),
            soil=_worst(soil_summary, labs),
            fieldOps=ops.status, risk=risk_alerts.status, forecast=yield_fc.status),
        crop=_crop(crop, latest, lang, now),
        campaign=_campaign(phenology),
        weather=_weather(agro, forecast3, wx_alerts),
        soil=_soil(soil_summary, labs, latest, operations),
        state=_state(latest, diseases, risk_alerts, parcel_urn),
        forecast=_forecast(yield_fc),
        nextJob=_next_job(latest),
        surprise=_surprise(latest),
        operations=operations[:10],
    )
