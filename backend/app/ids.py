"""Parcel id helpers: URN outward, short id only toward crop-health."""

import re

from nkz_platform_sdk.crop_timeline import normalize_parcel_urn

_PREFIX = "urn:ngsi-ld:AgriParcel:"
_VALID = re.compile(r"(?:urn:ngsi-ld:AgriParcel:)?[A-Za-z0-9._~-]+")


def is_valid(parcel_id: str) -> bool:
    """Short id or full URN; nothing that could change an upstream path or query."""
    return _VALID.fullmatch(parcel_id) is not None


def to_urn(parcel_id: str) -> str:
    return normalize_parcel_urn(parcel_id)


def to_short(parcel_id: str) -> str:
    return parcel_id[len(_PREFIX):] if parcel_id.startswith(_PREFIX) else parcel_id
