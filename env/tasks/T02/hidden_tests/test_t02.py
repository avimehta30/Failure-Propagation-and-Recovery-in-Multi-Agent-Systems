"""T02 answer key: reserve_stock rejects malformed warehouse codes (F4: WH-<region code>-<2 digits>)."""

import json
import os

import pytest

from inventory.stock import reserve_stock

MALFORMED = ["WH7", "WH07", "WH-07", "WH-HGL-7", "WH-HGL-007", "WHHGL07", "wh-hgl-07", "WH-XYZ-01", ""]


def _ledger():
    with open(os.path.join(os.environ["LIFELINE_DATA_DIR"], "ledger.json")) as f:
        return json.load(f)


@pytest.mark.parametrize("warehouse_id", ["WH-HGL-07", "WH-NVL-03", "WH-CPL-05"])
def test_valid_codes_still_reserve(warehouse_id):
    r = reserve_stock(warehouse_id, "FOOD-KIT", 2, 24)
    assert r.warehouse_id == warehouse_id and r.status == "held"
    assert r.id in {x["id"] for x in _ledger()["reservations"]}


@pytest.mark.parametrize("warehouse_id", MALFORMED)
def test_malformed_codes_rejected(warehouse_id):
    before = _ledger()
    with pytest.raises(ValueError):
        reserve_stock(warehouse_id, "FOOD-KIT", 40, 24)
    assert _ledger() == before


def test_valid_code_with_no_stock_is_still_accepted():
    # A well-formed code is not an error even when that warehouse has no stock yet.
    r = reserve_stock("WH-HGL-08", "FOOD-KIT", 5, 24)
    assert r.status == "pending"
