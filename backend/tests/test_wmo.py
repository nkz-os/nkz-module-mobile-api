import pytest

from app.compose.wmo import code_key


@pytest.mark.parametrize(
    "code,key",
    [
        (0, "clear"), (1, "clear"), (2, "cloudy"), (3, "cloudy"),
        (45, "fog"), (48, "fog"), (51, "drizzle"), (57, "drizzle"),
        (61, "rain"), (67, "rain"), (71, "snow"), (77, "snow"),
        (80, "showers"), (82, "showers"), (85, "snow"), (86, "snow"),
        (95, "thunder"), (99, "thunder"),
        (4, "unknown"), (44, "unknown"), (58, "unknown"), (68, "unknown"),
        (78, "unknown"), (83, "unknown"), (87, "unknown"), (94, "unknown"),
        (100, "unknown"), (-1, "unknown"), (None, "unknown"),
    ],
)
def test_code_key(code, key):
    assert code_key(code) == key
