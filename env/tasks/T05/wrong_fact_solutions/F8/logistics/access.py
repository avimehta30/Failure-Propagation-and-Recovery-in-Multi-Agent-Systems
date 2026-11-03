"""Road access. Field teams report each road's status as a one-letter code:

    A   open to all vehicles
    R   restricted: light vehicles only (vans); heavy trucks may not use it
    X   closed to all vehicles

Statuses are kept in data/network.json and updated as reports come in.
"""

from core import store

NETWORK = "network.json"

OPEN, RESTRICTED, CLOSED = "A", "R", "X"
STATUS_CODES = (OPEN, RESTRICTED, CLOSED)

VEHICLE_WEIGHT = {"truck": "heavy", "van": "light"}


def load_network() -> dict:
    return store.read_json(NETWORK)


def road_status(road_id: str, network: dict | None = None) -> str:
    network = network or load_network()
    if road_id not in network["roads"]:
        raise KeyError(f"unknown road {road_id!r}")
    status = network["roads"][road_id]["status"]
    if status not in STATUS_CODES:
        raise ValueError(f"road {road_id} has unknown status {status!r}")
    return status


def can_pass(road_id: str, vehicle: str, network: dict | None = None) -> bool:
    """May this vehicle use the road now? Only open roads can be used; R and X roads are closed."""
    return road_status(road_id, network) == OPEN
