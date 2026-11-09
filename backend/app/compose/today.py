"""Pure composition of TodayV1 from source results (spec 2.4). No I/O."""

from datetime import datetime, timezone
from typing import Any

from ..ids import to_urn
from ..schemas import Card, CardAction, CardPlain, TodaySources, TodaySummary, TodayV1
from ..sources.base import SourceResult
from ._util import _lower, _str, _unwrap, alert_is_active, alert_ref_urn

MAX_CARDS = 50
MAX_WEATHER = 5
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "severe": 4, "moderate": 5}
_VIBRATE_JOBS = {"irrigate", "sow", "treat"}
_RECORD_JOBS = {"irrigate", "sow", "treat", "harvest"}
_INFO_JOBS = {"pending_assessment", "none_until"}


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(res: SourceResult, key: str) -> list[dict]:
    if res.status != "ok" or not isinstance(res.data, dict):
        return []
    rows = res.data.get(key)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _plain(alert: dict, lang: str) -> CardPlain | None:
    plain = _unwrap(alert.get("plain"))
    if not isinstance(plain, dict):
        return None
    entry = plain.get(lang)
    if not isinstance(entry, dict) and isinstance(plain.get("lang"), dict):
        entry = plain["lang"].get(lang)
    if isinstance(entry, dict) and _str(entry.get("title")) and _str(entry.get("body")):
        return CardPlain(title=entry["title"], body=entry["body"])
    return None


def _open_parcel(urn: str | None) -> CardAction:
    return CardAction(kind="open_parcel", params={"parcelId": urn} if urn else {})


def _risk_cards(res: SourceResult, lang: str, now: str) -> list[Card]:
    cards: list[Card] = []
    for a in _rows(res, "alerts"):
        aid = _str(a.get("id"))
        if not aid or not alert_is_active(a):
            continue
        sev, cat = _lower(a.get("severity")), _lower(a.get("category"))
        atype = _lower(a.get("alertType")) or "unknown"
        urn = alert_ref_urn(a)
        name = _unwrap(a.get("refEntityName"))
        explicit = _lower(a.get("urgency"))
        if explicit in ("vibrate", "silent"):
            urgency = explicit
        else:
            urgency = "vibrate" if sev in ("high", "critical") and cat in ("disease", "pest") else "silent"
        at = _str(_unwrap(a.get("observedAt"))) or _str(_unwrap(a.get("validFrom"))) or now
        cards.append(Card(
            id=aid, kind="alert", urgency=urgency, parcelId=urn,
            parcelName=name if isinstance(name, str) and name else None,
            messageKey=f"card.alert.{atype}", params={"severity": sev, "category": cat},
            plain=_plain(a, lang), action=_open_parcel(urn), at=at))
    return cards


def _weather_cards(res: SourceResult, now: str) -> list[Card]:
    rows = [r for r in _rows(res, "alerts")
            if _lower(r.get("severity")) in ("severe", "moderate") and _str(r.get("id"))]
    rows.sort(key=lambda r: _str(r.get("validFrom")) or "", reverse=True)
    rows.sort(key=lambda r: _SEVERITY_RANK[_lower(r.get("severity"))])  # stable: severe first
    cards: list[Card] = []
    for r in rows[:MAX_WEATHER]:
        sev = _lower(r.get("severity"))
        cards.append(Card(
            id=r["id"], kind="alert", urgency="vibrate" if sev == "severe" else "silent",
            parcelId=None, parcelName=None, messageKey="card.alert.weather",
            params={"severity": sev, "headline": _str(r.get("description"))},
            plain=None, action=CardAction(kind="none", params={}),
            at=_str(r.get("validFrom")) or now))
    return cards


def _parcel_cards(res: SourceResult, now: str) -> tuple[list[Card], list[Card], list[Card], list[Card], int]:
    """Returns (jobs_today, jobs_other, surprises, info, no_data)."""
    today_c: list[Card] = []
    other: list[Card] = []
    surprises: list[Card] = []
    info: list[Card] = []
    no_data = 0
    for r in _rows(res, "parcels"):
        pid = _str(r.get("parcelId"))
        if r.get("hasData") is not True:
            no_data += 1
        if not pid:
            continue
        urn = to_urn(pid)
        name = _str(r.get("parcelName"))
        job = r.get("nextJob")
        if isinstance(job, dict) and _str(job.get("kind")):
            kind = job["kind"]
            when = _str(job.get("when"))  # may be absent: never invented
            detail = job["detail"] if isinstance(job.get("detail"), dict) else {}
            if kind in _INFO_JOBS:
                info.append(Card(
                    id=f"info:{urn}:{kind}", kind="info", urgency="silent", parcelId=urn,
                    parcelName=name, messageKey=f"card.job.{kind}", params={**detail, "when": when},
                    plain=None, action=_open_parcel(urn), at=now))
            else:
                card = Card(
                    id=f"job:{urn}:{kind}", kind="job",
                    urgency="vibrate" if kind in _VIBRATE_JOBS and when == "today" else "silent",
                    parcelId=urn, parcelName=name, messageKey=f"card.job.{kind}",
                    params={**detail, "when": when}, plain=None,
                    action=(CardAction(kind="record_operation", params={"parcelId": urn, "kind": kind})
                            if kind in _RECORD_JOBS else _open_parcel(urn)),
                    at=now)
                (today_c if when == "today" else other).append(card)
        s = r.get("surprise")
        if isinstance(s, dict) and _str(s.get("code")):
            detail = s["detail"] if isinstance(s.get("detail"), dict) else {}
            surprises.append(Card(
                id=f"surprise:{urn}:{s['code']}", kind="surprise", urgency="silent", parcelId=urn,
                parcelName=name, messageKey=f"card.surprise.{s['code']}", params=dict(detail),
                plain=None, action=_open_parcel(urn), at=now))
    return today_c, other, surprises, info, no_data


def _report_card(res: SourceResult) -> tuple[Card | None, str]:
    """Returns (card, source status). A malformed 200 is a failed source, never an error."""
    if res.status != "ok":
        return None, res.status
    d = res.data
    plain = d.get("plain") if isinstance(d, dict) else None
    rid, at = (_str(d.get("reportId")), _str(d.get("generatedAt"))) if isinstance(d, dict) else (None, None)
    if not rid or not isinstance(plain, dict) or not _str(plain.get("title")) or not _str(plain.get("body")):
        return None, "failed"
    return Card(
        id=f"weekly_report:{rid}", kind="weekly_report", urgency="silent", parcelId=None,
        parcelName=None, messageKey="card.weekly_report", params={},
        plain=CardPlain(title=plain["title"], body=plain["body"]),
        action=CardAction(kind="none", params={}), at=at or ""), "ok"


def build(*, now: datetime, lang: str, parcels: SourceResult, risk_alerts: SourceResult,
          wx_alerts: SourceResult, report: SourceResult = SourceResult("empty")) -> TodayV1:
    stamp = _iso(now)
    alerts = _risk_cards(risk_alerts, lang, stamp) + _weather_cards(wx_alerts, stamp)
    alerts.sort(key=lambda c: (c.urgency != "vibrate",
                               _SEVERITY_RANK.get(str(c.params.get("severity")), 9)))
    jobs_today, jobs_other, surprises, info, no_data = _parcel_cards(parcels, stamp)
    ordered = alerts + jobs_today + jobs_other + surprises + info
    report_card, report_status = _report_card(report)
    # The report card is the lowest tier but must survive the cap.
    cards = ordered[:MAX_CARDS - 1] + [report_card] if report_card else ordered[:MAX_CARDS]
    return TodayV1(
        generatedAt=stamp,
        sources=TodaySources(cropHealth=parcels.status, risk=risk_alerts.status,
                             weather=wx_alerts.status, notifications=report_status),
        cards=cards,
        summary=TodaySummary(alerts=len(alerts), jobsToday=len(jobs_today),
                             surprises=len(surprises), noData=no_data))
