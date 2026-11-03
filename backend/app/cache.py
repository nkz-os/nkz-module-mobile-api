"""Per-tenant in-memory TTL cache. Stores composed responses only, never identities."""

import time
from typing import Any, Callable


class TTLCache:
    def __init__(self, ttl_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._items: dict[tuple[str, str], tuple[float, Any]] = {}

    def get(self, tenant_id: str, key: str) -> Any | None:
        entry = self._items.get((tenant_id, key))
        if entry is None:
            return None
        expires, value = entry
        if self._clock() >= expires:
            self._items.pop((tenant_id, key), None)
            return None
        return value

    def set(self, tenant_id: str, key: str, value: Any) -> None:
        now = self._clock()
        if len(self._items) > 1024:  # opportunistic sweep keeps memory bounded
            self._items = {k: v for k, v in self._items.items() if v[0] > now}
        self._items[(tenant_id, key)] = (now + self._ttl, value)
