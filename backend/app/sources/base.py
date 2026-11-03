"""Source-call wrapper: every upstream call ends in a SourceResult, never an exception."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from ..config import Settings
from ..schemas import SourceStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceResult:
    status: SourceStatus
    data: Any = None
    error: str | None = None


def client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.source_timeout_s)


def _log(name: str, tenant: str, status: str, code: Any) -> None:
    logger.warning("source %s status=%s tenant=%s code=%s", name, status, tenant, code)


async def call(
    name: str,
    coro_factory: Callable[[], Awaitable[httpx.Response]],
    *,
    timeout_s: float,
    empty_on: tuple[int, ...] = (404,),
    tenant: str = "",
) -> SourceResult:
    try:
        resp = await asyncio.wait_for(coro_factory(), timeout_s)
    except (httpx.TimeoutException, asyncio.TimeoutError):
        _log(name, tenant, "timeout", "-")
        return SourceResult("timeout")
    except Exception as exc:  # noqa: BLE001 - boundary: nothing may escape
        _log(name, tenant, "failed", type(exc).__name__)
        return SourceResult("failed", error=type(exc).__name__)

    code = resp.status_code
    if code in empty_on:
        _log(name, tenant, "empty", code)
        return SourceResult("empty")
    if code in (401, 403):
        _log(name, tenant, "failed", code)
        return SourceResult("failed", error="auth")
    if code >= 400:
        _log(name, tenant, "failed", code)
        return SourceResult("failed", error=f"http_{code}")
    try:
        return SourceResult("ok", data=resp.json())
    except ValueError:
        _log(name, tenant, "failed", code)
        return SourceResult("failed", error="bad_json")


async def gather_with_budget(budget_s: float, **named: Awaitable[SourceResult]) -> dict[str, SourceResult]:
    tasks = {k: asyncio.ensure_future(v) for k, v in named.items()}
    try:
        if tasks:
            await asyncio.wait(tasks.values(), timeout=budget_s)
        out: dict[str, SourceResult] = {}
        for k, t in tasks.items():
            if t.done() and not t.cancelled() and t.exception() is None:
                out[k] = t.result()
            elif t.done() and not t.cancelled():
                out[k] = SourceResult("failed", error=type(t.exception()).__name__)
            else:
                out[k] = SourceResult("timeout", error="budget")
        return out
    finally:
        # Also runs when this coroutine is itself cancelled (client disconnect).
        pending = [t for t in tasks.values() if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
