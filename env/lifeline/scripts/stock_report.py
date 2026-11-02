"""Ops script: print usable stock per warehouse and SKU, and held reservations. Read-only.

Run from the Lifeline root:  python scripts/stock_report.py

Ops scripts live in this folder. Scripts that send payments or SMS, or change
data/registry.json or data/ledger.json, must say so in their docstring.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SKUS  # noqa: E402
from inventory.stock import available, load_ledger, reservations  # noqa: E402


def main() -> None:
    for warehouse in sorted(load_ledger()["warehouses"]):
        counts = ", ".join(f"{sku} {available(warehouse, sku)}" for sku in SKUS)
        print(f"{warehouse}: {counts}")
    for r in reservations("held"):
        print(f"held {r.id}: {r.qty} {r.sku} at {r.warehouse_id} until {r.expires_at}")


if __name__ == "__main__":
    main()
