import pytest

from app.ids import is_valid, to_short, to_urn

URN = "urn:ngsi-ld:AgriParcel:x"


def test_to_urn_and_short():
    assert to_urn("x") == URN
    assert to_urn(URN) == URN
    assert to_short(URN) == "x"
    assert to_short("x") == "x"


@pytest.mark.parametrize("pid", ["x", "p-1_a.b~c", URN, "urn:ngsi-ld:AgriParcel:Ab.9"])
def test_valid_ids(pid):
    assert is_valid(pid)


@pytest.mark.parametrize("pid", ["", "urn:x/../../../internal", "a/b", "a b", "a?x=1", "a#b",
                                 "urn:ngsi-ld:Other:x", "x\n", "%2e%2e", "a:b"])
def test_invalid_ids(pid):
    assert not is_valid(pid)
