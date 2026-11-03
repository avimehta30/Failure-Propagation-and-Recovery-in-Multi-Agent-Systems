"""Household registration: the list of everyone Lifeline is helping, stored in data/registry.json."""

import re

from config.settings import region_codes, today
from core import store
from core.ids import household_check_digit, make_household_id
from core.models import Household

REGISTRY = "registry.json"


def load_households(*, active_only: bool = False) -> list[Household]:
    households = [Household.from_dict(d) for d in store.read_json(REGISTRY)["households"]]
    return [h for h in households if h.status == "active"] if active_only else households


def save_households(households: list[Household]) -> None:
    store.write_json(REGISTRY, {"households": [h.to_dict() for h in households]})


def get_household(household_id: str) -> Household:
    for h in load_households():
        if h.id == household_id:
            return h
    raise KeyError(f"no household {household_id!r}")


def next_household_id(households: list[Household] | None = None) -> str:
    """The next unused household ID, skipping bases that have no valid check digit."""
    households = load_households() if households is None else households
    number = max((int(h.id[3:7]) for h in households), default=999) + 1
    while household_check_digit(f"{number:04d}") is None:
        number += 1
    return make_household_id(number)


def register_household(record: dict) -> Household:
    """Add a household to the registry. `record` uses the Household field names.

    If `id` is missing, the next free ID is assigned.
    """
    households = load_households()
    record = dict(record)
    if record.get("id") is None:
        record["id"] = next_household_id(households)
    record.setdefault("registered", today().isoformat())
    household = Household.from_dict(record)

    if not re.fullmatch(r"HH-\d{5}", household.id or ""):
        raise ValueError(f"{household.id} is not a valid household ID")
    if household.region not in region_codes():
        raise ValueError(f"unknown region {household.region!r}")
    if not household.members:
        raise ValueError("a household needs at least one member")
    if any(h.id == household.id for h in households):
        raise ValueError(f"household {household.id} is already registered")

    households.append(household)
    save_households(households)
    return household


def set_status(household_id: str, status: str, *, merged_into: str | None = None) -> Household:
    if status not in ("active", "inactive", "merged"):
        raise ValueError(f"unknown status {status!r}")
    households = load_households()
    for h in households:
        if h.id == household_id:
            h.status = status
            h.merged_into = merged_into
            save_households(households)
            return h
    raise KeyError(f"no household {household_id!r}")
