import json
from pathlib import Path

_UPSTREAM = Path(__file__).parent / "fixtures" / "upstream"


def load_fixture(relpath: str) -> dict:
    """relpath like 'crop_health/latest' (or with .json) under fixtures/upstream."""
    if not relpath.endswith(".json"):
        relpath += ".json"
    return json.loads((_UPSTREAM / relpath).read_text())
