"""Choosing which batch ("lot") of a product to take stock from.

Lifeline issues stock FEFO: first-expiring, first-out. The lot that expires soonest is
used first, whatever order the lots arrived in, so food does not spoil on the shelf.
"""

from datetime import date

from core.models import Lot


class InsufficientStock(Exception):
    pass


def usable(lot: Lot, today: date) -> bool:
    """A lot can be issued up to and including its expiry date."""
    return lot.qty > 0 and date.fromisoformat(lot.expires) >= today


def issue_order(lots: list[Lot], today: date) -> list[Lot]:
    """Usable lots in the order stock should be taken from them (FEFO)."""
    return sorted((l for l in lots if usable(l, today)), key=lambda l: (l.expires, l.received, l.id))


def pick_lots(lots: list[Lot], sku: str, qty: int, today: date) -> list[dict]:
    """Which lots to take `qty` units of `sku` from: [{"lot_id": ..., "qty": ...}, ...]."""
    picks, remaining = [], qty
    for lot in issue_order([l for l in lots if l.sku == sku], today):
        take = min(lot.qty, remaining)
        picks.append({"lot_id": lot.id, "qty": take})
        remaining -= take
        if remaining == 0:
            return picks
    raise InsufficientStock(f"only {qty - remaining} of {qty} {sku} available")
