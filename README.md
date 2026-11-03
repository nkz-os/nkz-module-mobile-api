# nkz-module-mobile-api

Backend-only module (FastAPI on `nkz-platform-sdk`) that composes existing platform APIs into
compact, app-ready responses for the mobile app. It owns no data and has no database.

Response schemas and rules: the phase-1 contract document in the platform's internal docs (section 2).

## Endpoints (prefix `/api/mobile`, gateway-authenticated)

| Route | Returns |
|---|---|
| `GET /today?lang=` | Cross-parcel summary of what needs attention today |
| `GET /parcels` | Parcel list with overall status level |
| `GET /briefing/{parcel_id}?lang=` | Per-parcel briefing composed from all sources |
| `GET /parcels/{parcel_id}/photos?since=&limit=` | Parcel photos |
| `GET /parcels/{parcel_id}/series?metric=&days=` | Metric time series (7, 30 or 90 days) |

`parcel_id` accepts the NGSI-LD URN or the short id; responses always carry the URN.
A failing source degrades to a per-source status, never a 5xx.

## Configuration (environment)

| Variable | Default | Purpose |
|---|---|---|
| `REQUIRE_HMAC_SIGNATURE` | `true` | Verify the gateway signature; startup fails if enabled without a secret |
| `HMAC_SECRET` | none | Shared gateway/backend secret |
| `CROP_HEALTH_URL` | in-cluster service | Crop-health source |
| `WEATHER_API_URL` | in-cluster service | Weather source |
| `SOIL_URL` | in-cluster service | Soil source |
| `FIELD_OPS_URL` | in-cluster service | Field-operations source |
| `RISK_URL` | in-cluster service | Risk source |
| `VEGETATION_URL` | in-cluster service | Vegetation source |
| `ORION_LD_URL` | SDK default | Context broker (parcel existence) |
| `ALLOWED_ORIGINS` | SDK default | CORS allowlist |
| `DEFAULT_LANG` | `es` | Language when `lang` is omitted |

## Local run and tests

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-test.txt
REQUIRE_HMAC_SIGNATURE=false .venv/bin/uvicorn app.main:app --port 8000
.venv/bin/python -m pytest -q
```

## Deploy checklist

1. Create the GitHub repository first, then push this code.
2. Build and push the first image from local (`docker build backend/`, tag `ghcr.io/<org>/nkz-module-mobile-api/mobile-api-backend:<tag>`).
3. Make the GHCR package public and grant the repository Actions write access (package settings, web UI).
4. Apply `k8s/registration.sql` on the platform database.
5. Pin the image digest in the gitops overlay (`k8s/` holds placeholder templates only).
6. Smoke test `GET /api/mobile/today` through the gateway with a valid session.

## License

AGPL-3.0.
