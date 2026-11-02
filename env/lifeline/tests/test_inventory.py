from datetime import date, datetime

import pytest

from core.models import Lot
from inventory.lots import InsufficientStock, issue_order, pick_lots
from inventory.stock import available, is_lapsed, load_ledger, release_stock, reservations, reserve_stock

DAY = date(2026, 3, 10)


def test_fefo_ignores_arrival_order():
    a = Lot("LOT-A", "WH-NVL-03", "FOOD-KIT", 10, received="2026-03-01", expires="2026-12-01")
    b = Lot("LOT-B", "WH-NVL-03", "FOOD-KIT", 10, received="2026-05-01", expires="2026-08-01")
    assert [l.id for l in issue_order([a, b], DAY)] == ["LOT-B", "LOT-A"]


def test_expired_and_empty_lots_skipped():
    old = Lot("LOT-O", "WH-NVL-03", "FOOD-KIT", 5, received="2025-01-01", expires="2026-03-09")
    empty = Lot("LOT-E", "WH-NVL-03", "FOOD-KIT", 0, received="2025-01-01", expires="2026-04-01")
    good = Lot("LOT-G", "WH-NVL-03", "FOOD-KIT", 5, received="2025-01-01", expires="2026-05-01")
    assert pick_lots([old, empty, good], "FOOD-KIT", 3, DAY) == [{"lot_id": "LOT-G", "qty": 3}]
    with pytest.raises(InsufficientStock):
        pick_lots([old, good], "FOOD-KIT", 6, DAY)


def test_reserve_takes_from_soonest_expiring_lot():
    before = available("WH-NVL-03", "FOOD-KIT")
    r = reserve_stock("WH-NVL-03", "FOOD-KIT", 3, 24)
    assert available("WH-NVL-03", "FOOD-KIT") == before - 3
    lots = {l["id"]: l for l in load_ledger()["lots"]}
    soonest = min((l for l in lots.values() if l["warehouse_id"] == "WH-NVL-03" and l["sku"] == "FOOD-KIT"
                   and l["expires"] >= "2026-03-10"), key=lambda l: l["expires"])
    assert r.lots[0]["lot_id"] == soonest["id"]
    assert r.expires_at == "2026-03-11T08:00:00"


def test_reserve_rejects_bad_arguments():
    with pytest.raises(ValueError):
        reserve_stock("FOOD-KIT", "WH-NVL-03", 3, 24)
    with pytest.raises(TypeError):
        reserve_stock("WH-NVL-03", "FOOD-KIT", 3)


def test_release_returns_stock():
    before = available("WH-CPL-05", "FOOD-KIT")
    r = reserve_stock("WH-CPL-05", "FOOD-KIT", 4, 12)
    release_stock(r.id)
    assert available("WH-CPL-05", "FOOD-KIT") == before
    with pytest.raises(ValueError):
        release_stock(r.id)


def test_lapsed_reservations():
    held = reservations("held")
    lapsed = [r for r in held if is_lapsed(r)]
    assert lapsed and len(lapsed) < len(held)
    assert not is_lapsed(lapsed[0], now=datetime(2026, 3, 1))
