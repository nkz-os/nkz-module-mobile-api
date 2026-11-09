"""Coercion helpers shared by the composers."""

from typing import Any

from ..ids import to_urn

# Parcel job kind -> operation type recorded by the `record_operation` card action.
RECORD_OPERATION_TYPE = {
    "irrigate": "irrigation",
    "sow": "sowing",
    "treat": "spraying",
    "harvest": "harvesting",
}


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


def _lower(v: Any) -> str | None:
    v = _unwrap(v)
    return v.lower() if isinstance(v, str) and v else None


def alert_is_active(alert: dict) -> bool:
    """A risk alert counts unless it carries a status other than 'active'."""
    status = _lower(alert.get("status"))
    return status is None or status == "active"


def alert_ref_urn(alert: dict) -> str | None:
    """Parcel URN a risk alert refers to (`refEntity`, any form), else None."""
    ref = _unwrap(alert.get("refEntity"))
    return to_urn(ref) if isinstance(ref, str) and ref else None


def record_operation_params(parcel_urn: str, kind: str) -> dict:
    """Params of a `record_operation` action; `operationType` only when the kind maps."""
    params: dict = {"parcelId": parcel_urn, "kind": kind}
    op_type = RECORD_OPERATION_TYPE.get(kind)
    if op_type is not None:
        params["operationType"] = op_type
    return params
