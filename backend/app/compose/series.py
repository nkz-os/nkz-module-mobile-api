"""Pure composition of SeriesV1 from one source result (spec 2.7). No I/O."""

from ..schemas import Metric, SeriesPoint, SeriesV1
from ..sources.base import SourceResult
from ._util import _num, _str

# metric -> (response list key, value field, unit)
_TABLE: dict[str, tuple[str, str, str]] = {
    "water_balance": ("points", "balance", "mm"),
    "cwsi": ("points", "cwsi", "ratio"),
    "rain": ("days", "precip_mm", "mm"),
    "tmax": ("days", "tmax_c", "°C"),
    "tmin": ("days", "tmin_c", "°C"),
    "vigor": ("points", "mean", "ndvi"),
}


def build(metric: Metric, days: int, raw: SourceResult) -> SeriesV1:
    key, field, unit = _TABLE[metric]
    rows = raw.data.get(key) if raw.status == "ok" and isinstance(raw.data, dict) else None
    points: list[SeriesPoint] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not _str(r.get("date")):
            continue
        points.append(SeriesPoint(date=r["date"], value=_num(r.get(field))))
    points.sort(key=lambda p: p.date)
    source = "empty" if raw.status == "ok" and not points else raw.status
    return SeriesV1(metric=metric, unit=unit, days=days, points=points, source=source)
