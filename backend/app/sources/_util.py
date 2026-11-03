"""Shared helpers for the thin upstream clients."""

from dataclasses import replace

from .base import SourceResult


def mark_empty(result: SourceResult, key: str) -> SourceResult:
    """A 200 whose main list is empty is reported as `empty`, not `ok`."""
    if result.status == "ok" and isinstance(result.data, dict):
        value = result.data.get(key)
        if isinstance(value, list) and not value:
            return replace(result, status="empty")
    return result
