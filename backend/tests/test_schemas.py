import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import BriefingV1, Light, ParcelsV1, PhotosV1, SeriesV1, TodayV1

FIX = Path(__file__).parent / "fixtures" / "contract"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


@pytest.mark.parametrize(
    "model,name",
    [
        (BriefingV1, "briefing_v1.json"),
        (TodayV1, "today_v1.json"),
        (ParcelsV1, "parcels_v1.json"),
        (PhotosV1, "photos_v1.json"),
        (SeriesV1, "series_v1.json"),
    ],
)
def test_fixture_roundtrip(model, name):
    data = load(name)
    # by_alias: BriefingV1.forecast uses the reserved word "yield" as alias
    assert model.model_validate(data).model_dump(by_alias=True) == data


def test_briefing_rejects_unknown_field():
    data = load("briefing_v1.json")
    data["surplus"] = 1
    with pytest.raises(ValidationError):
        BriefingV1.model_validate(data)


def test_briefing_rejects_unknown_nested_field():
    data = load("briefing_v1.json")
    data["soil"]["moisture"]["extra"] = 1
    with pytest.raises(ValidationError):
        BriefingV1.model_validate(data)


def test_light_level_enum():
    with pytest.raises(ValidationError):
        Light(level="green", messageKey="x")


def test_light_params_default_not_shared():
    a, b = Light(level="ok", messageKey="x"), Light(level="ok", messageKey="y")
    a.params["k"] = 1
    assert b.params == {}


def test_version_fixed_to_one():
    data = load("series_v1.json")
    data["version"] = 2
    with pytest.raises(ValidationError):
        SeriesV1.model_validate(data)


def test_briefing_allows_null_crop_names_and_weather_readings():
    data = load("briefing_v1.json")
    data["crop"].update(status="unknown", species=None, name=None)
    data["weather"]["now"] = {k: None for k in data["weather"]["now"]}
    model = BriefingV1.model_validate(data)
    assert model.crop.species is None and model.weather.now.tempC is None
    assert model.model_dump(by_alias=True) == data
