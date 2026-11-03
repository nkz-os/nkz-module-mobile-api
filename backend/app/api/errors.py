"""Uniform error body: {"error": "<code>"}."""

from fastapi.responses import JSONResponse


def bad_request(code: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": code})
