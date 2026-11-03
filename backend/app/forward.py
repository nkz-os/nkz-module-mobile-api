"""Identity forwarding: the five gateway headers plus the request id, copied as received."""

from dataclasses import dataclass
from typing import Any

from fastapi import Request

FORWARDED_HEADERS = (
    "Authorization", "X-Tenant-ID", "X-User-ID", "X-User-Roles", "X-Auth-Signature",
    "X-Request-ID",
)


@dataclass(frozen=True, eq=False)
class Identity:
    headers: dict[str, str]
    tenant_id: str

    @property
    def request_id(self) -> str:
        return self.headers.get("X-Request-ID", "")

    def __repr__(self) -> str:
        return f"Identity(tenant={self.tenant_id}, headers=<{len(self.headers)} keys>)"

    __str__ = __repr__


def from_request(request: Request, ctx: Any) -> Identity:
    headers: dict[str, str] = {}
    for name in FORWARDED_HEADERS:
        value = request.headers.get(name)  # case-insensitive lookup
        if value is not None:
            headers[name] = value
    return Identity(headers=headers, tenant_id=ctx.tenant_id)
