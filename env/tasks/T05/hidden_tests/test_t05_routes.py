"""T05 answer key, routing part: passable_route() and rerouted_sites() (F8)."""

import pytest

EXPECTED = {
    ("WH-NVL-03", "SITE-NVL-A"): ("RT-01", "truck"),
    ("WH-NVL-03", "SITE-NVL-B"): ("RT-02", "van"),      # shortest route has a restricted road
    ("WH-CPL-05", "SITE-CPL-A"): ("RT-04", "truck"),
    ("WH-CPL-05", "SITE-CPL-B"): ("RT-06", "van"),      # shortest route is closed
    ("WH-HGL-07", "SITE-HGL-A"): ("RT-08", "truck"),    # shortest route is closed
    ("WH-HGL-07", "SITE-HGL-B"): ("RT-09", "van"),      # only route is restricted
}


@pytest.mark.parametrize("warehouse,site", sorted(EXPECTED))
def test_passable_route(warehouse, site):
    from logistics.routes import passable_route
    route, vehicle = passable_route(warehouse, site)
    assert (route["id"], vehicle) == EXPECTED[(warehouse, site)]


def test_no_usable_route_and_no_route_at_all():
    from logistics.routes import passable_route
    net = {"roads": {"Z-1": {"status": "X"}}, "sites": {},
           "routes": [{"id": "RT-Z", "from": "WH-ZZZ-01", "to": "SITE-Z", "roads": ["Z-1"], "km": 5}]}
    assert passable_route("WH-ZZZ-01", "SITE-Z", net) is None
    assert passable_route("WH-NVL-03", "SITE-HGL-A") is None


def test_rerouted_sites():
    from logistics.routes import rerouted_sites
    assert rerouted_sites() == ["SITE-CPL-B", "SITE-HGL-A"]


def test_rerouted_sites_on_another_network():
    from logistics.routes import rerouted_sites
    net = {"roads": {"Z-1": {"status": "R"}, "Z-2": {"status": "A"}, "Z-3": {"status": "X"}}, "sites": {},
           "routes": [{"id": "RT-A", "from": "WH-ZZZ-01", "to": "SITE-A", "roads": ["Z-1"], "km": 5},
                      {"id": "RT-B", "from": "WH-ZZZ-01", "to": "SITE-B", "roads": ["Z-3"], "km": 5},
                      {"id": "RT-C", "from": "WH-ZZZ-01", "to": "SITE-B", "roads": ["Z-2"], "km": 9},
                      {"id": "RT-D", "from": "WH-ZZZ-01", "to": "SITE-C", "roads": ["Z-3"], "km": 5}]}
    assert rerouted_sites(net) == ["SITE-B"]
