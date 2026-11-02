from datetime import date

import pytest

from config.settings import load_regions, region, region_codes
from core.ids import format_warehouse_id, household_check_digit, make_household_id, next_number
from core.models import Household, Member


def test_regions():
    assert region_codes() == ["CPL", "HGL", "NVL"]
    assert region("NVL")["people_per_kit"] == 2
    assert all("cash_per_cycle" in r for r in load_regions().values())


def test_household_ids():
    assert make_household_id(1042) == "HH-10427"
    assert household_check_digit("1043") != 7


def test_some_bases_have_no_check_digit():
    assert household_check_digit("0001") is None
    with pytest.raises(ValueError):
        make_household_id(1)


def test_warehouse_ids():
    assert format_warehouse_id("HGL", 7) == "WH-HGL-07"
    with pytest.raises(ValueError):
        format_warehouse_id("XYZ", 1)


def test_next_number():
    assert next_number(["PAY-00003", "PAY-00010", "SMS-00099"], "PAY-") == 11
    assert next_number([], "RSV-") == 1


def test_member_age():
    m = Member("A", "2024-03-11")
    assert m.age_on(date(2026, 3, 10)) == 1
    assert m.age_on(date(2026, 3, 11)) == 2


def test_household_round_trip():
    d = {"id": "HH-10427", "region": "NVL", "site": "SITE-NVL-A", "phone": "+999 70000000",
         "members": [{"name": "A B", "birth_date": "1990-01-01", "pregnant": False}],
         "registered": "2026-01-01"}
    h = Household.from_dict(d)
    assert h.head.name == "A B" and Household.from_dict(h.to_dict()) == h
