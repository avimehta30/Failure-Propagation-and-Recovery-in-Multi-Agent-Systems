import pytest

from logistics.access import can_pass, load_network, road_status
from logistics.routes import best_route, trips_needed, vehicles_for


def test_road_codes():
    assert can_pass("A", "truck") and can_pass("A", "van")
    assert can_pass("R", "van") and not can_pass("R", "truck")
    assert not can_pass("X", "van")
    with pytest.raises(ValueError):
        can_pass("C", "van")


def test_restricted_route_is_van_only():
    net = load_network()
    route = next(r for r in net["routes"] if any(net["roads"][x]["status"] == "R" for x in r["roads"])
                 and all(net["roads"][x]["status"] != "X" for x in r["roads"]))
    assert vehicles_for(route, net) == ["van"]


def test_closed_route_unusable():
    net = load_network()
    route = next(r for r in net["routes"] if any(net["roads"][x]["status"] == "X" for x in r["roads"]))
    assert vehicles_for(route, net) == []


def test_best_route_prefers_shortest_usable():
    net = load_network()
    for site in net["sites"]:
        wh = next(r["from"] for r in net["routes"] if r["to"] == site)
        found = best_route(wh, site, net)
        assert found, f"{site} should be reachable"
        route, vehicle = found
        assert vehicle in vehicles_for(route, net)


def test_road_status_and_trips():
    assert road_status("R-12") == "X"
    assert trips_needed(41, "truck") == 2 and trips_needed(12, "van") == 1
