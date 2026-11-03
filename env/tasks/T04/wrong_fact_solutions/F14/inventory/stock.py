"""Warehouse stock and reservations, stored in data/ledger.json.

Reserving stock sets units aside for a delivery: they are taken out of their lots
straight away and held for `hold_hours`. Releasing a reservation puts the units back.
If there is not enough stock yet, the reservation is recorded as "pending" and nothing
is taken; it waits for new stock to arrive.

The ledger also keeps a waiting list: households still waiting for stock to be reserved.
"""

from dataclasses import asdict
from datetime import datetime, timedelta

from config.settings import SKUS
from config.settings import now as _now
from core import store
from core.ids import format_reservation_id, next_number
from core.models import Lot, Reservation
from inventory.lots import InsufficientStock, pick_lots, usable

LEDGER = "ledger.json"


def load_ledger() -> dict:
    return store.read_json(LEDGER)


def save_ledger(ledger: dict) -> None:
    store.write_json(LEDGER, ledger)


def _lots(ledger: dict, warehouse_id: str) -> list[Lot]:
    return [Lot(**l) for l in ledger["lots"] if l["warehouse_id"] == warehouse_id]


def available(warehouse_id: str, sku: str, today=None) -> int:
    day = today or _now().date()
    return sum(l.qty for l in _lots(load_ledger(), warehouse_id) if l.sku == sku and usable(l, day))


def reserve_stock(warehouse_id: str, sku: str, qty: int, hold_hours: int, *,
                  household_id: str | None = None, now=None) -> Reservation:
    """Hold `qty` units of `sku` at `warehouse_id` for `hold_hours` hours."""
    if sku not in SKUS:
        raise ValueError(f"unknown SKU {sku!r}")
    if qty <= 0 or hold_hours <= 0:
        raise ValueError("qty and hold_hours must be positive")
    ledger = load_ledger()
    when = now or _now()
    try:
        picks, status = pick_lots(_lots(ledger, warehouse_id), sku, qty, when.date()), "held"
    except InsufficientStock:
        picks, status = [], "pending"
    taken = {p["lot_id"]: p["qty"] for p in picks}
    for lot in ledger["lots"]:
        lot["qty"] -= taken.get(lot["id"], 0)

    reservation = Reservation(
        id=format_reservation_id(next_number([r["id"] for r in ledger["reservations"]], "RSV-")),
        warehouse_id=warehouse_id, sku=sku, qty=qty, lots=picks, status=status,
        created=when.isoformat(timespec="seconds"),
        expires_at=(when + timedelta(hours=hold_hours)).isoformat(timespec="seconds"),
        household_id=household_id)
    ledger["reservations"].append(asdict(reservation))
    save_ledger(ledger)
    return reservation


def release_stock(reservation_id: str) -> Reservation:
    """Cancel a held or pending reservation; held units go back to the lots they came from."""
    ledger = load_ledger()
    for r in ledger["reservations"]:
        if r["id"] == reservation_id:
            if r["status"] not in ("held", "pending"):
                raise ValueError(f"reservation {reservation_id} is already {r['status']}")
            back = {p["lot_id"]: p["qty"] for p in r["lots"]}
            for lot in ledger["lots"]:
                lot["qty"] += back.get(lot["id"], 0)
            r["status"] = "released"
            save_ledger(ledger)
            return Reservation(**r)
    raise KeyError(f"no reservation {reservation_id!r}")


def reservations(status: str | None = None) -> list[Reservation]:
    return [Reservation(**r) for r in load_ledger()["reservations"]
            if status is None or r["status"] == status]


def waiting_list() -> list[dict]:
    """Households waiting for stock: [{"household_id", "warehouse_id", "sku", "qty"}, ...]."""
    return list(load_ledger().get("waiting", []))


WINTER_KIT_HOLD_HOURS = 72


def reserve_winter_kits(warehouse_id: str, qty: int, household_id: str) -> Reservation | None:
    """Hold `qty` winter kits at `warehouse_id` for a household; nothing to hold when qty is 0."""
    if qty == 0:
        return None
    return reserve_stock("WINTER-KIT", warehouse_id, qty)
