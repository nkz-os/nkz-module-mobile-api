"""Closed v1 vocabulary of field-photo tags (stored in the record's `category`)."""

from typing import Any

PHOTO_TAGS = ("pest", "disease", "weed", "damage", "crop_status", "soil_water", "other")

# Orion may return a term compact or expanded to its full IRI.
_CATEGORY_KEYS = ("category", "https://smartdatamodels.org/dataModel.Agrifood/category")
_LEGACY_TAG_KEYS = ("tag", "https://uri.etsi.org/ngsi-ld/default-context/tag")


def normalize_tag(value: Any) -> str | None:
    """None if absent; the tag if in the vocabulary; otherwise "other"."""
    if not isinstance(value, str) or not value:
        return None
    return value if value in PHOTO_TAGS else "other"


def tag_of(entity: dict) -> str | None:
    """`category` first, then the legacy `tag`, each in compact or IRI form."""
    for key in _CATEGORY_KEYS + _LEGACY_TAG_KEYS:
        tag = normalize_tag(entity.get(key))
        if tag is not None:
            return tag
    return None
