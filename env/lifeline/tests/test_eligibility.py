from datetime import date

from core.models import Household
from eligibility.rules import is_eligible, programs, threshold_for
from eligibility.scoring import score_breakdown, vulnerability_score

DAY = date(2026, 3, 10)


def _hh(members, **flags):
    return Household.from_dict({"id": "HH-10427", "region": "NVL", "site": "SITE-NVL-A", "phone": "+999 7",
                                "members": members, "registered": "2026-01-01", **flags})


ADULT = {"name": "A", "birth_date": "1990-01-01", "pregnant": False}
PREGNANT = {"name": "B", "birth_date": "1995-01-01", "pregnant": True}


def test_score_parts():
    h = _hh([ADULT], shelter_damaged=True, income_lost=True)
    assert score_breakdown(h, DAY) == {"shelter_damaged": 20, "income_lost": 15}
    assert vulnerability_score(h, DAY) == 35


def test_thresholds():
    assert threshold_for(_hh([ADULT])) == 60
    assert threshold_for(_hh([ADULT, PREGNANT])) == 45


def test_eligibility_at_the_edges():
    # 20 + 15 + 15 + 8 = 58: not enough without a pregnancy
    kid = {"name": "C", "birth_date": "2023-01-01", "pregnant": False}
    h = _hh([ADULT, kid], shelter_damaged=True, income_lost=True, disability=True)
    assert vulnerability_score(h, DAY) == 58 and not is_eligible(h, today=DAY)
    # 20 + 15 + 10 (pregnant) = 45: just qualifies
    p = _hh([ADULT, PREGNANT], shelter_damaged=True, disability=True)
    assert vulnerability_score(p, DAY) == 45 and is_eligible(p, today=DAY)


def test_programs():
    h = _hh([ADULT, PREGNANT], shelter_damaged=True, income_lost=True, disability=True)
    assert programs(h, DAY) == ["food", "cash", "shelter"]
    h.status = "inactive"
    assert programs(h, DAY) == []
