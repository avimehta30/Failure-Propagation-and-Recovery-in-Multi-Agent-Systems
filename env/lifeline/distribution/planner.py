"""The distribution plan: one food delivery per enrolled household, with warehouse, route and vehicle.

This is where the separate steps meet: registry (who), eligibility (qualifies?),
allocation (how much), inventory (from where) and logistics (how to get there).
Building a plan changes nothing; stock is reserved separately.
"""

from collections import defaultdict

from allocation.rations import food_kits
from config.settings import today as _today
from core.models import Delivery
from eligibility.rules import programs
from inventory.stock import available, load_ledger
from logistics.access import load_network
from logistics.routes import best_route, trips_needed
from registry.register import load_households


def warehouse_for(region: str, ledger: dict) -> str:
    """The warehouse that serves a region (each region has one)."""
    matches = sorted(w for w, info in ledger["warehouses"].items() if info["region"] == region)
    if not matches:
        raise KeyError(f"no warehouse serves region {region!r}")
    return matches[0]


def build_plan(today=None) -> list[Delivery]:
    day = today or _today()
    ledger, network = load_ledger(), load_network()
    plan = []
    for hh in load_households(active_only=True):
        if "food" not in programs(hh, today=day):
            continue
        warehouse = warehouse_for(hh.region, ledger)
        delivery = Delivery(household_id=hh.id, warehouse_id=warehouse, site=hh.site,
                            sku="FOOD-KIT", kits=food_kits(hh, today=day))
        found = best_route(warehouse, hh.site, network)
        if found:
            delivery.route_id, delivery.vehicle = found[0]["id"], found[1]
        else:
            delivery.status = "unreachable"
        plan.append(delivery)
    return sorted(plan, key=lambda d: d.household_id)


def site_summary(plan: list[Delivery]) -> dict[str, dict]:
    """Kits and trips per distribution site."""
    out: dict[str, dict] = defaultdict(lambda: {"households": 0, "kits": 0, "trips": 0, "unreachable": 0})
    for d in plan:
        s = out[d.site]
        s["households"] += 1
        s["kits"] += d.kits
        if d.status == "unreachable":
            s["unreachable"] += 1
        else:
            s["trips"] += trips_needed(d.kits, d.vehicle)
    return dict(out)


def shortfalls(plan: list[Delivery], today=None) -> dict[str, int]:
    """Kits missing per warehouse if the whole plan were reserved now."""
    need: dict[str, int] = defaultdict(int)
    for d in plan:
        if d.status == "planned":
            need[d.warehouse_id] += d.kits
    return {w: n - available(w, "FOOD-KIT", today) for w, n in need.items()
            if n > available(w, "FOOD-KIT", today)}
