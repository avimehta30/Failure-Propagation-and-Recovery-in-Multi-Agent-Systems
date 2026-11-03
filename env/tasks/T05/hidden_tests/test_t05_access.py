"""T05 answer key, road access part: can_pass() (F8: A open, R light vehicles only, X closed)."""

import pytest


@pytest.mark.parametrize("road,vehicle,expected", [
    ("R-01", "truck", True), ("R-01", "van", True),      # A
    ("R-03", "truck", False), ("R-03", "van", True),     # R
    ("R-08", "truck", False), ("R-08", "van", False),    # X
])
def test_can_pass_by_road_status(road, vehicle, expected):
    from logistics.access import can_pass
    assert can_pass(road, vehicle) is expected


def test_can_pass_uses_the_given_network():
    from logistics.access import can_pass
    net = {"roads": {"Z-1": {"status": "R"}, "Z-2": {"status": "A"}, "Z-3": {"status": "X"}}, "routes": [], "sites": {}}
    assert [can_pass(r, "van", net) for r in ("Z-1", "Z-2", "Z-3")] == [True, True, False]
    assert [can_pass(r, "truck", net) for r in ("Z-1", "Z-2", "Z-3")] == [False, True, False]
