"""Frozen v1 response contract of the mobile API (spec 2026-11-03, section 2).

Field names are camelCase on purpose: they are the wire format.
Dates and timestamps are ISO strings, passed through untouched.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SourceStatus = Literal["ok", "empty", "failed", "timeout"]
LightLevel = Literal["ok", "warn", "bad", "unknown"]
WeatherSemaphore = Literal[
    "optimal", "satisfied", "caution", "deficit", "not_suitable",
    "too_wet", "too_dry", "alert", "unknown",
]
CodeKey = Literal[
    "clear", "cloudy", "fog", "drizzle", "rain", "snow", "showers", "thunder", "unknown",
]
Urgency = Literal["vibrate", "silent"]
CardKind = Literal["alert", "job", "surprise", "info"]
ActionKind = Literal["open_parcel", "record_operation", "ask_assistant", "none"]
Metric = Literal["water_balance", "cwsi", "rain", "tmax", "tmin", "vigor"]
Freshness = Literal["fresh", "aging", "stale", "none"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Light(_Model):
    level: LightLevel
    messageKey: str
    params: dict[str, Any] = Field(default_factory=dict)


# --- briefing ---------------------------------------------------------------

class BriefingSources(_Model):
    cropHealth: SourceStatus
    weather: SourceStatus
    soil: SourceStatus
    fieldOps: SourceStatus
    risk: SourceStatus
    forecast: SourceStatus


class PlannedCrop(_Model):
    species: str
    name: str
    sowingDate: str


class Crop(_Model):
    status: Literal["active", "none", "unknown"]
    species: str | None = None
    name: str | None = None
    variety: str | None
    sowingDate: str | None
    provenance: Literal["actual", "declared", "planned"] | None
    daysSinceSowing: int | None
    plannedCrop: PlannedCrop | None


class Campaign(_Model):
    stage: str
    progressPct: float | None
    deviation: float | str | None
    gddAccumulated: float | None
    dataFidelity: str


class WeatherNow(_Model):
    observedAt: str | None
    tempC: float | None
    humidityPct: float | None
    windMs: float | None
    precipMm: float | None


class WeatherSemaphores(_Model):
    spraying: WeatherSemaphore
    workability: WeatherSemaphore
    irrigation: WeatherSemaphore


class WeatherDay(_Model):
    date: str
    tminC: float
    tmaxC: float
    precipMm: float
    precipProbPct: float | None
    code: int
    codeKey: CodeKey


class WeatherAlert(_Model):
    severity: str
    headline: str
    validFrom: str
    validTo: str


class Weather(_Model):
    now: WeatherNow | None
    semaphores: WeatherSemaphores
    days: list[WeatherDay]
    alerts: list[WeatherAlert]


class Topsoil(_Model):
    depthFrom: float
    depthTo: float
    sandPct: float | None
    clayPct: float | None
    siltPct: float | None
    organicMatterPct: float | None


class SoilMoisture(_Model):
    level: Literal["none", "moderate", "high", "critical", "unknown"]
    ratio: float | None


class LabAnalysis(_Model):
    date: str
    reference: str


class LastOperation(_Model):
    type: str
    date: str
    status: str


class Operation(_Model):
    id: str
    type: str
    date: str
    status: str


class Soil(_Model):
    textureClass: str | None
    topsoil: Topsoil | None
    moisture: SoilMoisture
    lastLabAnalysis: LabAnalysis | None
    lastOperation: LastOperation | None


class State(_Model):
    water: Light
    plant: Light
    risks: Light
    overall: Light
    assessedAt: str | None
    freshness: Freshness


class YieldValue(_Model):
    value: float
    unit: str
    low: float | None
    high: float | None


class YieldForecast(_Model):
    # "yield" is a Python keyword: attribute `yield_`, wire name "yield".
    # Dump with by_alias=True (FastAPI does by default).
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    yield_: YieldValue = Field(alias="yield")
    harvestDate: str | None
    computedAt: str


class NextJob(_Model):
    kind: str
    when: str | None
    detail: dict[str, Any]


class Surprise(_Model):
    code: str
    detail: dict[str, Any]


class BriefingV1(_Model):
    version: Literal[1] = 1
    parcelId: str
    parcelName: str | None
    generatedAt: str
    lang: Literal["es", "eu", "en"]
    sources: BriefingSources
    crop: Crop | None
    campaign: Campaign | None
    weather: Weather | None
    soil: Soil | None
    state: State | None
    forecast: YieldForecast | None
    nextJob: NextJob | None
    surprise: Surprise | None
    operations: list[Operation]


# --- today ------------------------------------------------------------------

class TodaySources(_Model):
    cropHealth: SourceStatus
    risk: SourceStatus
    weather: SourceStatus


class CardPlain(_Model):
    title: str
    body: str


class CardAction(_Model):
    kind: ActionKind
    params: dict[str, Any] = Field(default_factory=dict)


class Card(_Model):
    id: str
    kind: CardKind
    urgency: Urgency
    parcelId: str | None
    parcelName: str | None
    messageKey: str
    params: dict[str, Any] = Field(default_factory=dict)
    plain: CardPlain | None
    action: CardAction
    at: str


class TodaySummary(_Model):
    alerts: int
    jobsToday: int
    surprises: int
    noData: int


class TodayV1(_Model):
    version: Literal[1] = 1
    generatedAt: str
    sources: TodaySources
    cards: list[Card]
    summary: TodaySummary


# --- parcels ----------------------------------------------------------------

class ParcelsSources(_Model):
    cropHealth: SourceStatus
    risk: SourceStatus


class ParcelRow(_Model):
    parcelId: str
    parcelName: str
    areaHa: float | None
    cropName: str | None
    stage: str | None
    overall: Light
    assessedAt: str | None
    freshness: Freshness


class ParcelsV1(_Model):
    version: Literal[1] = 1
    generatedAt: str
    sources: ParcelsSources
    parcels: list[ParcelRow]


# --- photos -----------------------------------------------------------------

class Photo(_Model):
    id: str
    imageUrl: str
    capturedAt: str
    note: str | None
    tag: str | None  # pest|disease|weed|damage|crop_status|soil_water|other, or null (app.tags.PHOTO_TAGS)
    location: list[float] | None = Field(default=None, min_length=2, max_length=2)  # [lng, lat]
    accuracyM: float | None


class PhotosV1(_Model):
    version: Literal[1] = 1
    source: SourceStatus
    photos: list[Photo]


# --- series -----------------------------------------------------------------

class SeriesPoint(_Model):
    date: str
    value: float | None


class SeriesV1(_Model):
    version: Literal[1] = 1
    metric: Metric
    unit: str
    days: Literal[7, 30, 90]
    points: list[SeriesPoint]
    source: SourceStatus
