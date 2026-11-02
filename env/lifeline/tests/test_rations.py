from datetime import date

from allocation.rations import food_kits, ration_size
from core.models import Household

DAY = date(2026, 3, 10)


def _hh(ages_in_days):
    members = [{"name": f"M{i}", "birth_date": date.fromordinal(DAY.toordinal() - d).isoformat(),
                "pregnant": False} for i, d in enumerate(ages_in_days)]
    return Household.from_dict({"id": "HH-10427", "region": "HGL", "site": "SITE-HGL-A",
                                "phone": "+999 7", "members": members, "registered": "2026-01-01"})


ADULT, INFANT = 30 * 365, 200


def test_infants_count_half():
    assert ration_size(_hh([ADULT] * 4 + [INFANT] * 2), DAY) == 5.0


def test_kits_round_down():
    assert food_kits(_hh([ADULT] * 4 + [INFANT] * 2), DAY) == 2
    assert food_kits(_hh([ADULT] * 7), DAY) == 3


def test_minimum_one_kit():
    assert food_kits(_hh([INFANT]), DAY) == 1
