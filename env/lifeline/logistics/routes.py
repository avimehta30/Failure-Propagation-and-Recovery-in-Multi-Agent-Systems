"""Routes from warehouses to distribution sites, and which vehicle to send.

A route is a fixed list of roads (see data/network.json). A vehicle can take a route
only if it may pass every road on it.
"""

import math

from logistics.access import can_pass, load_network

# Kits one vehicle carries per trip. Trucks are preferred when the roads allow them.
CAPACITY = {"truck": 40, "van": 12}
PREFERENCE = ("truck", "van")


def vehicles_for(route: dict, network: dict) -> list[str]:
    """Vehicles that can drive the whole route, most preferred first."""
    return [v for v in PREFERENCE
            if all(can_pass(network["roads"][r]["status"], v) for r in route["roads"])]


def routes_between(warehouse_id: str, site: str, network: dict) -> list[dict]:
    return [r for r in network["routes"] if r["from"] == warehouse_id and r["to"] == site]


def best_route(warehouse_id: str, site: str, network: dict | None = None) -> tuple[dict, str] | None:
    """Shortest usable route and the vehicle to send, or None if the site is unreachable."""
    network = network or load_network()
    options = [(r, vehicles_for(r, network)) for r in routes_between(warehouse_id, site, network)]
    options = [(r, v[0]) for r, v in options if v]
    if not options:
        return None
    return min(options, key=lambda o: (o[0]["km"], o[0]["id"]))


def trips_needed(kits: int, vehicle: str) -> int:
    return math.ceil(kits / CAPACITY[vehicle])


def site_distance(warehouse_id: str, site: str, network: dict | None = None) -> float | None:
    """Length in km of the best usable route, or None if unreachable."""
    found = best_route(warehouse_id, site, network)
    return found[0]["km"] if found else None
