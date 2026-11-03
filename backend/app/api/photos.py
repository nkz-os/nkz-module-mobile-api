"""GET {prefix}/parcels/{parcel_id}/photos - field photos from Orion records."""

import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request

from ..auth import identity
from ..compose._util import _num, _str
from ..ids import to_urn
from ..schemas import Photo, PhotosV1
from ..sources import orion

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
    pid, url = _str(e.get("id")), _str(e.get("imageUrl"))
    if not pid or not url:
        return None
    return Photo(id=pid, imageUrl=_relative(url), capturedAt=_str(e.get("dateObserved")) or "",
                 note=_str(e.get("note")), tag=_str(e.get("tag")),
                 location=_location(e.get("location")), accuracyM=_num(e.get("accuracy")))


@router.get("/parcels/{parcel_id:path}/photos", response_model=PhotosV1)
async def get_photos(request: Request, parcel_id: str, since: str | None = Query(default=None),
                     limit: str = Query(default="50"), ctx=identity):
    try:
        n = int(limit)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_limit")
    if not 1 <= n <= 200:
        raise HTTPException(status_code=400, detail="invalid_limit")
    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_since")
    urn = to_urn(parcel_id)
    res = await orion.photos(request.app.orion(ctx), urn, since_dt, n)
    rows = res.data if res.status == "ok" and isinstance(res.data, list) else []
    photos = [p for p in (_photo(e) for e in rows if isinstance(e, dict)) if p]
    logger.info("photos tenant=%s urn=%s n=%d source=%s", ctx.tenant_id, urn, len(photos), res.status)
    return PhotosV1(photos=photos)
