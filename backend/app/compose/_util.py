"""Coercion helpers shared by the composers."""

from typing import Any


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
