import json
from datetime import datetime, timezone
from pathlib import Path

from app.compose.briefing import build
from app.sources.base import SourceResult

FX = Path(__file__).parent / "fixtures" / "compose" / "briefing_full"
URN = "urn:ngsi-ld:AgriParcel:p1"
NOW = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
NAMES = ["crop", "latest", "diseases", "phenology", "agro", "forecast3", "wx_alerts",
         "soil_summary", "labs", "ops", "risk_alerts", "yield_fc"]


def srcs(**over):
    out = {n: SourceResult("ok", data=json.loads((FX / f"{n}.json").read_text())) for n in NAMES}
    for k, v in over.items():
        out[k] = v if isinstance(v, SourceResult) else SourceResult("ok", data=v)
    return out


def run(lang="es", name="Norte", **over):
    return build(parcel_urn=URN, parcel_name=name, lang=lang, now=NOW, **srcs(**over))


def test_full():
    b = run()
    assert b.version == 1 and b.parcelId == URN and b.parcelName == "Norte"
    assert b.generatedAt == "2026-11-03T08:00:00Z"
    assert b.sources.model_dump() == {k: "ok" for k in
                                      ("cropHealth", "weather", "soil", "fieldOps", "risk", "forecast")}
    c = b.crop
    assert (c.status, c.species, c.name, c.variety, c.sowingDate, c.provenance, c.daysSinceSowing) == \
        ("active", "TRZAX", "Trigo", "Marius", "2026-10-20", "actual", 14)
    assert c.plannedCrop.name == "Cebada" and c.plannedCrop.species == "HORVX"
    assert b.campaign.stage == "tillering" and b.campaign.progressPct == 62.5
    assert b.campaign.gddAccumulated == 512.4 and b.campaign.dataFidelity == "parcel_weather"
    w = b.weather
    assert w.now.tempC == 11.4 and w.now.observedAt == "2026-11-03T07:00:00Z"
    assert w.semaphores.spraying == "optimal" and w.semaphores.irrigation == "unknown"
    assert [d.codeKey for d in w.days] == ["clear", "rain", "thunder"]
    assert w.days[1].precipProbPct == 70.0 and w.days[1].code == 61
    assert [a.headline for a in w.alerts] == ["Heavy rain expected"]  # incomplete alert dropped
    s = b.soil
    assert s.textureClass == "clay loam" and s.topsoil.organicMatterPct == 1.724
    assert s.moisture.level == "moderate" and s.moisture.ratio == 0.45
    assert s.lastLabAnalysis.reference == "LAB-1"
    assert (s.lastOperation.type, s.lastOperation.date) == ("tillage", "2026-10-25T08:00:00Z")
    st = b.state
    assert st.water.level == "warn" and st.risks.level == "bad"
    assert st.risks.params == {"disease": "crop_stress"}  # only this parcel's risk alert counts
    assert st.overall.level == "bad" and st.freshness == "fresh"
    assert st.assessedAt == "2026-11-02T04:00:00Z"
    assert b.forecast.yield_.value == 3200.0 and b.forecast.yield_.unit == "kg/ha"
    assert b.forecast.harvestDate == "2027-06-20" and b.forecast.computedAt == "2026-11-02T02:00:00Z"
    assert b.nextJob.kind == "irrigate" and b.surprise.code == "frost_risk"
    dumped = b.model_dump(by_alias=True)
    assert "yield" in dumped["forecast"]


def test_operations_sorted_desc_by_ended_or_started():
    b = run()
    # o3 started 10-25, o2 ended 10-16, o1 ended 10-10; the op without dates is dropped
    assert [o.id for o in b.operations] == ["o3", "o2", "o1"]
    assert b.operations[0].date == "2026-10-25T08:00:00Z"


def test_operations_capped_at_ten():
    rows = [{"id": f"o{i}", "operationType": "t", "status": "completed",
             "startedAt": f"2026-10-{i + 1:02d}T00:00:00Z"} for i in range(15)]
    assert len(run(ops={"operations": rows}).operations) == 10


def test_crop_health_failed():
    f = SourceResult("failed", error="http_500")
    b = run(crop=f, latest=f, diseases=f, phenology=f)
    assert b.state is None and b.nextJob is None and b.surprise is None and b.campaign is None
    assert b.crop.status == "unknown" and b.crop.plannedCrop is None
    assert b.sources.cropHealth == "failed"
    assert b.soil.moisture.level == "unknown"  # soil still composed from soil/field-ops


def test_crop_source_failure_only_marks_crop_unknown():
    b = run(crop=SourceResult("failed"))
    assert b.crop.status == "unknown" and b.sources.cropHealth == "failed"
    assert b.state is not None


def test_source_status_worst_of():
    b = run(agro=SourceResult("empty"), forecast3=SourceResult("timeout"),
            soil_summary=SourceResult("failed"), labs=SourceResult("empty"))
    assert b.sources.weather == "timeout" and b.sources.soil == "failed"
    b2 = run(phenology=SourceResult("empty"))
    assert b2.sources.cropHealth == "empty" and b2.campaign is None


def test_soil_empty_keeps_crop_health_moisture():
    b = run(soil_summary=SourceResult("empty"), labs=SourceResult("empty"))
    assert b.soil.topsoil is None and b.soil.moisture.level == "moderate"
    assert b.soil.textureClass == "clay loam"  # from latest.soilProperties


def test_perennial_without_sowing_date():
    b = run(crop={"timeline": {"current": {"species": "OLEEU", "start": {"date": None, "provenance": "actual"}}},
                  "variety": None})
    assert b.crop.status == "active" and b.crop.sowingDate is None
    assert b.crop.daysSinceSowing is None and b.crop.provenance == "actual"


def test_no_current_crop():
    b = run(crop={"timeline": {"current": None}, "variety": None})
    assert b.crop.status == "none" and b.crop.species is None
    assert b.crop.plannedCrop is not None


def test_forecast_not_validated():
    assert run(yield_fc={"status": "not_validated", "estimates": [], "computed_at": "x"}).forecast is None
    assert run(yield_fc={"status": "done", "estimates": [], "computed_at": "x"}).forecast is None


def test_forecast_defaults():
    b = run(yield_fc={"status": "done", "computed_at": "2026-11-02T02:00:00Z",
                      "harvestDate": "2027-06-01", "estimates": [{"value": 5.0}]})
    assert b.forecast.yield_.unit == "t/ha" and b.forecast.yield_.low is None
    assert b.forecast.harvestDate == "2027-06-01"


def test_planned_crop_name_fallbacks():
    def planned(names):
        return {"assessments": [], "plannedCrop": {"species": "HORVX", "names": names,
                                                   "sowingDate": "2026-11-20"}}
    assert run(lang="eu", latest=planned({"es": "Cebada"})).crop.plannedCrop.name == "Cebada"
    assert run(lang="en", latest=planned({"en": "Barley", "es": "Cebada"})).crop.plannedCrop.name == "Barley"
    assert run(lang="en", latest=planned({})).crop.plannedCrop.name == "HORVX"


def test_weather_rows_missing_values_dropped():
    rows = [{"date": "2026-11-03", "temp_max": 1, "temp_min": 0, "weather_code": 1, "precip_mm": 0, "precip_probability": 1},
            {"date": "2026-11-04", "temp_max": 1, "temp_min": 0, "weather_code": 1, "precip_probability": 1},
            {"temp_max": 1, "temp_min": 0, "weather_code": 1, "precip_mm": 0, "precip_probability": 1}]
    assert [d.date for d in run(forecast3={"forecast": rows}).weather.days] == ["2026-11-03"]


def test_weather_none_when_all_weather_sources_down():
    e = SourceResult("failed")
    assert run(agro=e, forecast3=e, wx_alerts=e).weather is None


def test_parcel_name_fallback_and_ref_forms():
    assert run(name=None).parcelName == "Norte"  # from the crop-health assessment
    alerts = {"alerts": [{"alertType": "frost", "severity": "high", "refEntity": "p1"}]}
    assert run(risk_alerts=alerts).state.risks.level == "bad"
    obj = {"alerts": [{"alertType": "frost", "severity": "high", "refEntity": {"object": URN}}]}
    assert run(risk_alerts=obj).state.risks.level == "bad"
