"""GET {prefix}/parcels/{parcel_id}/photos - field photos from Orion records."""

import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..auth import identity
from .errors import bad_request
from ..compose._util import _num, _str
from ..forward import from_request
from ..ids import is_valid, to_urn
from ..schemas import Photo, PhotosV1
from ..sources import orion
from ..tags import PHOTO_TAGS, tag_of

logger = logging.getLogger(__name__)
router = APIRouter()


def _relative(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return urlsplit(url).path
    return url


def _location(v: Any) -> list[float] | None:
    coords = v.get("coordinates") if isinstance(v, dict) else None
    if isinstance(coords, list) and len(coords) >= 2:
        lng, lat = _num(coords[0]), _num(coords[1])
        if lng is not None and lat is not None:
            return [lng, lat]
    return None


def _photo(e: dict) -> Photo | None:
    pid, url, at = _str(e.get("id")), _str(e.get("imageUrl")), _str(e.get("dateObserved"))
    if not pid or not url or not at:
        return None
    return Photo(id=pid, imageUrl=_relative(url), capturedAt=at,
                 note=_str(e.get("note")), tag=tag_of(e),
                 location=_location(e.get("location")), accuracyM=_num(e.get("accuracy")))


@router.get("/parcels/{parcel_id:path}/photos", response_model=PhotosV1)
async def get_photos(request: Request, parcel_id: str, since: str | None = Query(default=None),
                     limit: str = Query(default="50"), tag: str | None = Query(default=None),
                     ctx=identity):
    if not is_valid(parcel_id):
        return bad_request("invalid_parcel_id")
    try:
        n = int(limit)
    except ValueError:
        return bad_request("invalid_limit")
    if not 1 <= n <= 200:
        return bad_request("invalid_limit")
    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            return bad_request("invalid_since")
    if tag is not None and tag not in PHOTO_TAGS:
        return bad_request("invalid_tag")
    urn = to_urn(parcel_id)
    client = request.app.orion(ctx)
    rid = from_request(request, ctx).request_id
    exists = await orion.parcel_exists(client, urn, rid)
    if exists.status == "empty":
        return JSONResponse(status_code=404, content={"error": "parcel_not_found"})
    res = await orion.photos(client, urn, since_dt, n, rid, tag)
    rows = res.data if res.status == "ok" and isinstance(res.data, list) else []
    photos = [p for p in (_photo(e) for e in rows if isinstance(e, dict)) if p]
    logger.info("photos tenant=%s urn=%s n=%d source=%s", ctx.tenant_id, urn, len(photos), res.status)
    return PhotosV1(photos=photos, source=res.status)
