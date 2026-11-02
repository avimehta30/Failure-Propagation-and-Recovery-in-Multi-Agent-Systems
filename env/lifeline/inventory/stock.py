"""Warehouse stock and reservations, stored in data/ledger.json.

Reserving stock sets units aside for a delivery: they are taken out of their lots
straight away and held for `hold_hours`. Releasing a reservation puts the units back.
"""

from dataclasses import asdict
from datetime import datetime, timedelta

from config.settings import SKUS
from config.settings import now as _now
from core import store
from core.ids import format_reservation_id, next_number
from core.models import Lot, Reservation
from inventory.lots import InsufficientStock, pick_lots, usable  # noqa: F401  (re-exported)

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


def reserve_stock(warehouse_id: str, sku: str, qty: int, hold_hours: int, *, now=None) -> Reservation:
    """Hold `qty` units of `sku` at `warehouse_id` for `hold_hours` hours."""
    ledger = load_ledger()
    if warehouse_id not in ledger["warehouses"]:
        raise ValueError(f"unknown warehouse {warehouse_id!r}")
    if sku not in SKUS:
        raise ValueError(f"unknown SKU {sku!r}")
    if qty <= 0 or hold_hours <= 0:
        raise ValueError("qty and hold_hours must be positive")

    when = now or _now()
    picks = pick_lots(_lots(ledger, warehouse_id), sku, qty, when.date())
    taken = {p["lot_id"]: p["qty"] for p in picks}
    for lot in ledger["lots"]:
        lot["qty"] -= taken.get(lot["id"], 0)

    reservation = Reservation(
        id=format_reservation_id(next_number([r["id"] for r in ledger["reservations"]], "RSV-")),
        warehouse_id=warehouse_id, sku=sku, qty=qty, lots=picks,
        created=when.isoformat(timespec="seconds"),
        expires_at=(when + timedelta(hours=hold_hours)).isoformat(timespec="seconds"))
    ledger["reservations"].append(asdict(reservation))
    save_ledger(ledger)
    return reservation


def release_stock(reservation_id: str) -> Reservation:
    """Cancel a held reservation and return its units to the lots they came from."""
    ledger = load_ledger()
    for r in ledger["reservations"]:
        if r["id"] == reservation_id:
            if r["status"] != "held":
                raise ValueError(f"reservation {reservation_id} is {r['status']}, not held")
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


def is_lapsed(reservation: Reservation, now=None) -> bool:
    """True when a held reservation is past its hold time."""
    return reservation.status == "held" and datetime.fromisoformat(reservation.expires_at) < (now or _now())
