from app.ids import to_short, to_urn

URN = "urn:ngsi-ld:AgriParcel:x"


def test_to_urn_and_short():
    assert to_urn("x") == URN
    assert to_urn(URN) == URN
    assert to_short(URN) == "x"
    assert to_short("x") == "x"
