"""WMO weather-code to coarse key (fixed ranges; the app translates the key)."""

from app.schemas import CodeKey

_RANGES: tuple[tuple[int, int, CodeKey], ...] = (
    (0, 1, "clear"),
    (2, 3, "cloudy"),
    (45, 48, "fog"),
    (51, 57, "drizzle"),
    (61, 67, "rain"),
    (71, 77, "snow"),
    (80, 82, "showers"),
    (85, 86, "snow"),
    (95, 99, "thunder"),
)


def code_key(code: int | None) -> CodeKey:
    if code is None:
        return "unknown"
    for lo, hi, key in _RANGES:
        if lo <= code <= hi:
            return key
    return "unknown"
