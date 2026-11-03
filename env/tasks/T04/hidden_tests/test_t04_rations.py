"""T04 answer key, allocation part: winter_kits() (F1: under-2s count as 0.5; F2: round down).

These tests use their own region settings, so they do not depend on the settings part of
the ticket, and they check that the decision follows the winter_kit setting, not the climate.
"""

import pytest
import yaml

import config.settings as settings
from core.models import Household, Member

REGIONS = {"regions": {
    "AAA": {"name": "Warm with kits", "climate": "temperate", "winter_kit": {"people_per_kit": 3}},
    "BBB": {"name": "Cold without kits", "climate": "cold"},
    "CCC": {"name": "Plain", "climate": "temperate"},
    "DDD": {"name": "Small kits", "climate": "cold", "winter_kit": {"people_per_kit": 2}},
}}

ADULT, INFANT = "1985-05-01", "2025-08-01"     # on the operation date (2026-03-10): 40 years and 0 years


@pytest.fixture(autouse=True)
def regions(tmp_path, monkeypatch):
    path = tmp_path / "regions.yaml"
    path.write_text(yaml.safe_dump(REGIONS))
    monkeypatch.setattr(settings, "REGIONS_FILE", path)


def _household(region, adults, infants=0):
    members = [Member(f"Person {i}", ADULT) for i in range(adults)] + \
              [Member(f"Baby {i}", INFANT) for i in range(infants)]
    return Household(id="HH-10421", region=region, site="SITE-X", phone="+999 70000000",
                     members=members, registered="2026-01-05")


def _kits(*args):
    from allocation.rations import winter_kits
    return winter_kits(_household(*args))


@pytest.mark.parametrize("adults,infants,expected", [
    (6, 0, 2),    # 6 people / 3
    (4, 0, 1),    # 1.33 -> 1 (partial kits are dropped)
    (7, 0, 2),    # 2.33 -> 2
    (4, 2, 1),    # 4 + 0.5 + 0.5 = 5 people -> 1.67 -> 1
    (7, 2, 2),    # 8 people -> 2.67 -> 2
    (1, 0, 1),    # always at least one kit
])
def test_kits_follow_food_kit_household_rules(adults, infants, expected):
    assert _kits("AAA", adults, infants) == expected


def test_people_per_kit_comes_from_the_setting():
    assert _kits("DDD", 5, 0) == 2      # 5 / 2 = 2.5 -> 2
    assert _kits("DDD", 3, 2) == 2      # 4 people / 2


def test_no_setting_means_no_kits_even_if_cold():
    assert _kits("BBB", 6, 0) == 0
    assert _kits("CCC", 6, 0) == 0
