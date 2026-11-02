"""Road access. Field teams report each road's status as a one-letter code:

    A   open to all vehicles
    R   restricted: light vehicles only (vans); heavy trucks may not use it
    X   closed to all vehicles
"""

from core import store

NETWORK = "network.json"

OPEN, RESTRICTED, CLOSED = "A", "R", "X"

VEHICLE_WEIGHT = {"truck": "heavy", "van": "light"}


def load_network() -> dict:
    return store.read_json(NETWORK)


def road_status(road_id: str, network: dict | None = None) -> str:
    network = network or load_network()
    if road_id not in network["roads"]:
        raise KeyError(f"unknown road {road_id!r}")
    return network["roads"][road_id]["status"]


def can_pass(status: str, vehicle: str) -> bool:
    """Whether `vehicle` may use a road with this status code."""
    if vehicle not in VEHICLE_WEIGHT:
        raise ValueError(f"unknown vehicle {vehicle!r}")
    if status == OPEN:
        return True
    if status == RESTRICTED:
        return VEHICLE_WEIGHT[vehicle] == "light"
    if status == CLOSED:
        return False
    raise ValueError(f"unknown road status {status!r}")
