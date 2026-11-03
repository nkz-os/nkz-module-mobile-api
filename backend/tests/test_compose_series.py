import pytest

from app.compose import series as compose
from app.sources.base import SourceResult


def ok(key, rows):
    return SourceResult("ok", data={key: rows})


@pytest.mark.parametrize("metric,key,field,unit", [
    ("water_balance", "points", "balance", "mm"),
    ("cwsi", "points", "cwsi", "ratio"),
    ("rain", "days", "precip_mm", "mm"),
    ("tmax", "days", "tmax_c", "°C"),
    ("tmin", "days", "tmin_c", "°C"),
    ("vigor", "points", "mean", "ndvi"),
])
def test_metric_table(metric, key, field, unit):
    raw = ok(key, [{"date": "2026-11-02", field: 2.5}, {"date": "2026-11-01", field: 1}])
    out = compose.build(metric, 7, raw)
    assert out.version == 1 and out.metric == metric and out.unit == unit and out.days == 7
    assert [(p.date, p.value) for p in out.points] == [("2026-11-01", 1.0), ("2026-11-02", 2.5)]
    assert out.source == "ok"


def test_none_and_bad_values_kept_as_null_bad_dates_dropped():
    raw = ok("points", [{"date": "2026-11-01", "balance": None}, {"date": "2026-11-02", "balance": "x"},
                        {"balance": 3}, "junk"])
    out = compose.build("water_balance", 30, raw)
    assert [(p.date, p.value) for p in out.points] == [("2026-11-01", None), ("2026-11-02", None)]


def test_other_metric_fields_ignored():
    raw = ok("points", [{"date": "2026-11-01", "balance": 1, "cwsi": 0.4}])
    assert compose.build("cwsi", 7, raw).points[0].value == 0.4


@pytest.mark.parametrize("status", ["failed", "timeout", "empty"])
def test_non_ok_status_passthrough(status):
    out = compose.build("rain", 90, SourceResult(status))
    assert out.points == [] and out.source == status


def test_ok_with_empty_list_is_empty():
    assert compose.build("vigor", 7, ok("points", [])).source == "empty"
