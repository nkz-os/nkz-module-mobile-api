"""Parcel id helpers: URN outward, short id only toward crop-health."""

from nkz_platform_sdk.crop_timeline import normalize_parcel_urn

_PREFIX = "urn:ngsi-ld:AgriParcel:"


def to_urn(parcel_id: str) -> str:
    return normalize_parcel_urn(parcel_id)


def to_short(parcel_id: str) -> str:
    return parcel_id[len(_PREFIX):] if parcel_id.startswith(_PREFIX) else parcel_id
