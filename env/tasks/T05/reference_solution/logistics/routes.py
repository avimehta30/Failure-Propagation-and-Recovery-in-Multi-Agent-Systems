"""Routes from warehouses to distribution sites, and which vehicle to send.

A route is a fixed list of roads (see data/network.json), with its length in km.
"""

import math

from logistics.access import can_pass, load_network

# Kits one vehicle carries per trip. Trucks carry the most, so they are sent by default.
CAPACITY = {"truck": 40, "van": 12}
DEFAULT_VEHICLE = "truck"


def routes_between(warehouse_id: str, site: str, network: dict) -> list[dict]:
    return [r for r in network["routes"] if r["from"] == warehouse_id and r["to"] == site]


def best_route(warehouse_id: str, site: str, network: dict | None = None) -> tuple[dict, str] | None:
    """Shortest route from the warehouse to the site and the vehicle to send, or None if no route exists."""
    network = network or load_network()
    options = routes_between(warehouse_id, site, network)
    if not options:
        return None
    return min(options, key=lambda r: (r["km"], r["id"])), DEFAULT_VEHICLE


def sites_served(warehouse_id: str, network: dict | None = None) -> list[str]:
    """Sites that have at least one route from this warehouse, in name order."""
    network = network or load_network()
    return sorted({r["to"] for r in network["routes"] if r["from"] == warehouse_id})


def trips_needed(kits: int, vehicle: str) -> int:
    return math.ceil(kits / CAPACITY[vehicle])


def passable_route(warehouse_id: str, site: str, network: dict | None = None) -> tuple[dict, str] | None:
    """Shortest route the vehicle can use on every road: a truck if allowed, otherwise a van; None if none."""
    network = network or load_network()
    for route in sorted(routes_between(warehouse_id, site, network), key=lambda r: (r["km"], r["id"])):
        for vehicle in ("truck", "van"):
            if all(can_pass(road, vehicle, network) for road in route["roads"]):
                return route, vehicle
    return None


def rerouted_sites(network: dict | None = None) -> list[str]:
    """Sites whose shortest route can no longer be used but that still have a usable route, in name order."""
    network = network or load_network()
    sites = set()
    for warehouse_id, site in {(r["from"], r["to"]) for r in network["routes"]}:
        shortest, _ = best_route(warehouse_id, site, network)
        usable = passable_route(warehouse_id, site, network)
        if usable and usable[0]["id"] != shortest["id"]:
            sites.add(site)
    return sorted(sites)
