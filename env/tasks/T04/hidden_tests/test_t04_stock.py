"""T04 answer key, stock part: reserve_winter_kits() (F14: reserve_stock(warehouse_id, sku, qty, hold_hours))."""

import json
import os
from datetime import datetime, timedelta


def _ledger():
    with open(os.path.join(os.environ["LIFELINE_DATA_DIR"], "ledger.json")) as f:
        return json.load(f)


def _winter_units(ledger, warehouse_id):
    return sum(l["qty"] for l in ledger["lots"] if l["warehouse_id"] == warehouse_id and l["sku"] == "WINTER-KIT")


def test_reserves_winter_kits_for_72_hours():
    from inventory.stock import reserve_winter_kits
    before = _ledger()
    reserve_winter_kits("WH-HGL-07", 3, "HH-10421")
    after = _ledger()
    new = [r for r in after["reservations"] if r["id"] not in {x["id"] for x in before["reservations"]}]
    assert len(new) == 1
    r = new[0]
    assert (r["warehouse_id"], r["sku"], r["qty"], r["household_id"], r["status"]) == \
           ("WH-HGL-07", "WINTER-KIT", 3, "HH-10421", "held")
    assert datetime.fromisoformat(r["expires_at"]) - datetime.fromisoformat(r["created"]) == timedelta(hours=72)
    assert _winter_units(after, "WH-HGL-07") == _winter_units(before, "WH-HGL-07") - 3


def test_returns_the_reservation():
    from inventory.stock import reserve_winter_kits
    r = reserve_winter_kits("WH-HGL-07", 2, "HH-10421")
    assert r.sku == "WINTER-KIT" and r.qty == 2 and r.id in {x["id"] for x in _ledger()["reservations"]}


def test_warehouse_without_winter_stock_records_a_pending_hold():
    from inventory.stock import reserve_winter_kits
    r = reserve_winter_kits("WH-NVL-03", 2, "HH-10421")
    assert (r.warehouse_id, r.sku, r.status) == ("WH-NVL-03", "WINTER-KIT", "pending")


def test_zero_kits_reserves_nothing():
    from inventory.stock import reserve_winter_kits
    before = _ledger()
    assert reserve_winter_kits("WH-HGL-07", 0, "HH-10421") is None
    assert _ledger() == before
