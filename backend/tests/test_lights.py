import pytest

from app.compose import lights
from app.schemas import Light


def kl(light):
    return light.level, light.messageKey


def test_no_assessment_is_unknown():
    for fn in (lights.water, lights.plant):
        assert fn(None) == Light(level="unknown", messageKey="state.unknown")
        assert fn(None).params == {}


@pytest.mark.parametrize(
    "a,expected",
    [
        ({"recommendedAction": "IRRIGATE_IMMEDIATE"}, ("bad", "state.water.irrigate_now")),
        ({"soilWaterBalance": {"stressLevel": "critical"}}, ("bad", "state.water.irrigate_now")),
        # priority: first matching row wins
        ({"recommendedAction": "IRRIGATE_SCHEDULED", "soilWaterBalance": {"stressLevel": "critical"}},
         ("bad", "state.water.irrigate_now")),
        ({"recommendedAction": "IRRIGATE_SCHEDULED"}, ("warn", "state.water.irrigate_soon")),
        ({"soilWaterBalance": {"stressLevel": "high"}}, ("warn", "state.water.irrigate_soon")),
        ({"soilWaterBalance": {"stressLevel": "moderate"}}, ("warn", "state.water.irrigate_soon")),
        ({"waterloggingRisk": {"riskLevel": "high"}}, ("warn", "state.water.too_wet")),
        ({"waterloggingRisk": {"riskLevel": "critical"}}, ("warn", "state.water.too_wet")),
        ({"soilWaterBalance": {"stressLevel": "moderate"}, "waterloggingRisk": {"riskLevel": "high"}},
         ("warn", "state.water.irrigate_soon")),
        ({"recommendedAction": "NO_ACTION", "soilWaterBalance": {"stressLevel": "none"},
          "waterloggingRisk": {"riskLevel": "low"}}, ("ok", "state.water.ok")),
        ({"recommendedAction": None, "soilWaterBalance": None, "waterloggingRisk": None},
         ("ok", "state.water.ok")),
    ],
)
def test_water(a, expected):
    assert kl(lights.water(a)) == expected


def test_water_empty_assessment_is_unknown():
    assert kl(lights.water({})) == ("unknown", "state.unknown")


@pytest.mark.parametrize(
    "a,expected,params",
    [
        ({"compositeStressIndex": 60, "dominantStressor": "drought"}, ("bad", "state.plant.stressed"), {"stressor": "drought"}),
        ({"compositeStressIndex": 59.9}, ("ok", "state.plant.ok"), {}),
        ({"compositeStressIndex": 85}, ("bad", "state.plant.stressed"), {"stressor": None}),
        ({"thermalSeverity": "high", "frostHours": 0}, ("bad", "state.plant.heat"), {}),
        ({"thermalSeverity": "critical"}, ("bad", "state.plant.heat"), {}),
        ({"thermalSeverity": "high", "frostHours": 3}, ("bad", "state.plant.frost"), {}),
        ({"vigorCondition": "below_expected"}, ("warn", "state.plant.vigor_low"), {}),
        ({"vigorCondition": "anomalous_senescence"}, ("warn", "state.plant.vigor_low"), {}),
        ({"vigorCondition": "below_expected", "compositeStressIndex": 70, "dominantStressor": "heat"},
         ("bad", "state.plant.stressed"), {"stressor": "heat"}),
        ({"vigorCondition": "normal", "compositeStressIndex": 10, "thermalSeverity": "low"},
         ("ok", "state.plant.ok"), {}),
        ({"compositeStressIndex": None, "thermalSeverity": None}, ("ok", "state.plant.ok"), {}),
    ],
)
def test_plant(a, expected, params):
    light = lights.plant(a)
    assert kl(light) == expected
    assert light.params == params


def test_risks_disease_high_is_bad():
    light = lights.risks([{"risk_level": "HIGH", "disease": "mildew"}], [], True)
    assert kl(light) == ("bad", "state.risks.treat")
    assert light.params == {"disease": "mildew"}


def test_risks_critical_wins_over_medium():
    light = lights.risks([{"risk_level": "MEDIUM", "disease": "a"}, {"risk_level": "CRITICAL", "disease": "b"}], None, True)
    assert kl(light) == ("bad", "state.risks.treat")
    assert light.params == {"disease": "b"}


def test_risks_alert_high_is_bad_even_if_sources_not_ok():
    light = lights.risks(None, [{"severity": "high", "disease": "rust"}], False)
    assert kl(light) == ("bad", "state.risks.treat")


def test_risks_medium_is_warn():
    assert kl(lights.risks([{"risk_level": "MEDIUM", "disease": "m"}], [], True)) == ("warn", "state.risks.watch")
    assert kl(lights.risks([], [{"severity": "medium", "disease": "m"}], True)) == ("warn", "state.risks.watch")


def test_risks_low_only_is_ok():
    assert kl(lights.risks([{"risk_level": "LOW", "disease": "x"}], [{"severity": "low"}], True)) == ("ok", "state.risks.ok")


def test_risks_empty_sources_ok_is_ok():
    assert kl(lights.risks([], [], True)) == ("ok", "state.risks.ok")
    assert kl(lights.risks(None, None, True)) == ("ok", "state.risks.ok")


def test_risks_no_data_sources_down_is_unknown():
    assert kl(lights.risks(None, None, False)) == ("unknown", "state.unknown")
    assert kl(lights.risks([], [], False)) == ("unknown", "state.unknown")


def _l(level, key):
    return Light(level=level, messageKey=key, params={"k": key})


def test_overall_worst_wins():
    ok, unk, warn, bad = _l("ok", "a"), _l("unknown", "b"), _l("warn", "c"), _l("bad", "d")
    assert lights.overall(ok, unk, warn, bad) == bad
    assert lights.overall(ok, unk, warn) == warn
    assert lights.overall(ok, unk) == unk
    assert lights.overall(ok, _l("ok", "z")) == ok


def test_overall_tie_keeps_first():
    assert lights.overall(_l("warn", "first"), _l("warn", "second")).messageKey == "first"


def test_overall_single_and_params():
    only = _l("bad", "x")
    assert lights.overall(only).params == {"k": "x"}


@pytest.mark.parametrize(
    "sev,level",
    [("LOW", "ok"), ("MEDIUM", "warn"), ("HIGH", "bad"), ("CRITICAL", "bad"),
     ("weird", "unknown"), (None, "unknown"), ("", "unknown")],
)
def test_severity_to_level(sev, level):
    assert lights.severity_to_level(sev) == level


def test_risks_ignores_non_dict_items():
    from app.compose import lights

    out = lights.risks([1, "x", None, ["a"], {"risk_level": "high", "disease": "mildew"}],
                       ["y", 2, {"severity": "critical", "alertType": "frost"}], True)
    assert out.level == "bad" and out.params == {"disease": "mildew"}
    assert lights.risks([1, "x"], [None], True).level == "ok"


def _frost(severity="high", lead=3, tmin=-2.0, **extra):
    ev = {"text_lead": lead, "text_tmin_c": tmin}
    ev.update(extra)
    return {"alertType": "frost", "severity": severity, "evaluationData": ev}


def test_frost_high_several_nights_ahead_is_amber():
    light = lights.risks(None, [_frost("high", lead=3, tmin=-3.0)], True)
    assert kl(light) == ("warn", "state.risks.frost_watch")
    assert light.params == {}


def test_frost_low_severity_near_is_amber():
    assert kl(lights.risks(None, [_frost("low", lead=2, tmin=-1.0)], True)) == ("warn", "state.risks.frost_watch")


def test_frost_critical_is_red_even_far_ahead():
    assert kl(lights.risks(None, [_frost("critical", lead=4, tmin=-6.0)], True)) == ("bad", "state.risks.frost_act")


@pytest.mark.parametrize("lead", [0, 1])
def test_frost_tonight_below_zero_is_red(lead):
    assert kl(lights.risks(None, [_frost("high", lead=lead, tmin=-0.5)], True)) == ("bad", "state.risks.frost_act")


def test_frost_tonight_not_below_zero_is_amber():
    assert kl(lights.risks(None, [_frost("high", lead=1, tmin=0.0)], True)) == ("warn", "state.risks.frost_watch")


def test_frost_missing_evaluation_data_is_amber_never_red():
    for a in ({"alertType": "frost", "severity": "high"},
              {"alertType": "frost", "severity": "high", "evaluationData": None},
              {"alertType": "frost", "severity": "high", "evaluationData": {"text_tmin_c": -3}},
              {"alertType": "frost", "severity": "high", "evaluationData": {"text_lead": 0}},
              {"alertType": "frost", "severity": "high", "evaluationData": {"text_lead": "0", "text_tmin_c": "x"}}):
        assert kl(lights.risks(None, [a], True)) == ("warn", "state.risks.frost_watch")


def test_frost_wrapped_evaluation_data_is_read():
    a = {"alertType": "frost", "severity": "high",
         "evaluationData": {"type": "Property", "value": {"text_lead": 1, "text_tmin_c": -1.0}}}
    assert kl(lights.risks(None, [a], True)) == ("bad", "state.risks.frost_act")


def test_disease_alert_unchanged_and_no_frost_code():
    light = lights.risks(None, [{"alertType": "mildew", "severity": "high"}], True)
    assert kl(light) == ("bad", "state.risks.treat")
    assert light.params == {"disease": "mildew"}


def test_two_frost_alerts_worst_wins():
    far = _frost("high", lead=3, tmin=-3.0)
    tonight = _frost("high", lead=1, tmin=-1.0)
    for order in ([far, tonight], [tonight, far]):
        assert kl(lights.risks(None, order, True)) == ("bad", "state.risks.frost_act")
    assert kl(lights.risks(None, [far, _frost("medium", lead=2, tmin=-1.0)], True)) == ("warn", "state.risks.frost_watch")


def test_frost_amber_does_not_hide_disease_red():
    light = lights.risks([{"risk_level": "high", "disease": "mildew"}], [_frost()], True)
    assert kl(light) == ("bad", "state.risks.treat")

