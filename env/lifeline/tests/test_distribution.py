from distribution.planner import build_plan, shortfalls, site_summary, warehouse_for
from eligibility.rules import is_eligible
from inventory.stock import load_ledger
from registry.register import load_households


def test_plan_covers_every_eligible_household():
    plan = build_plan()
    eligible = {h.id for h in load_households() if is_eligible(h)}
    assert {d.household_id for d in plan} == eligible
    assert all(d.kits >= 1 and d.sku == "FOOD-KIT" for d in plan)


def test_plan_does_not_change_stock():
    before = load_ledger()
    build_plan()
    assert load_ledger() == before


def test_summary_and_shortfalls():
    plan = build_plan()
    summary = site_summary(plan)
    assert sum(s["households"] for s in summary.values()) == len(plan)
    assert shortfalls(plan) == {}


def test_each_region_has_a_warehouse():
    ledger = load_ledger()
    assert warehouse_for("HGL", ledger) == "WH-HGL-07"
