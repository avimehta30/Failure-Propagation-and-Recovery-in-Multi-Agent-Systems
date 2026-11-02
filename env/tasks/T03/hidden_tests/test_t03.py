"""T03 answer key: needs_review flags households within 5 points below their cutoff (F7: 60, or 45 if pregnant)."""

import pytest

from core.models import Household
from eligibility.rules import needs_review
from eligibility.scoring import vulnerability_score
from registry.register import load_households

ADULT, PREGNANT = ("1990-01-01", False), ("1990-01-01", True)
KID, ELDER = ("2023-01-01", False), ("1950-01-01", False)       # under 5, over 65 on 2026-03-10


def _hh(people, **flags):
    members = [{"name": f"M{i}", "birth_date": b, "pregnant": p} for i, (b, p) in enumerate(people)]
    return Household.from_dict({"id": "HH-19992", "region": "NVL", "site": "SITE-NVL-A", "phone": "+999 7",
                                "members": members, "registered": "2026-01-01", **flags})


CASES = [
    # (household, expected score, flagged?)
    (_hh([ADULT, KID, KID, KID], shelter_damaged=True, income_lost=True), 59, True),
    (_hh([ADULT, KID, KID, ELDER, ELDER], shelter_damaged=True), 56, True),
    (_hh([ADULT, ELDER, ELDER], disability=True, shelter_damaged=True), 55, True),
    (_hh([ADULT, KID, KID, KID, ELDER], shelter_damaged=True), 54, False),
    (_hh([ADULT, ELDER], shelter_damaged=True, income_lost=True, disability=True), 60, False),
    (_hh([ADULT], shelter_damaged=True, income_lost=True, disability=True), 50, False),
    (_hh([PREGNANT, KID, KID, KID, ELDER]), 44, True),
    (_hh([PREGNANT], disability=True, income_lost=True), 40, True),
    (_hh([PREGNANT, KID], shelter_damaged=True), 38, False),
    (_hh([PREGNANT], shelter_damaged=True, income_lost=True), 45, False),
    (_hh([PREGNANT, KID, ELDER], shelter_damaged=True), 48, False),
]


@pytest.mark.parametrize("household,score,flagged", CASES, ids=[f"score{c[1]}-{'preg' if c[0].members[0].pregnant else 'std'}" for c in CASES])
def test_scores_around_both_cutoffs(household, score, flagged):
    assert vulnerability_score(household) == score
    assert needs_review(household) is flagged


def test_registry_flags_exactly_the_near_misses():
    def expected(h):
        cutoff = 45 if any(m.pregnant for m in h.members) else 60
        return cutoff - 5 <= vulnerability_score(h) < cutoff
    active = [h for h in load_households() if h.status == "active"]
    assert any(expected(h) for h in active)
    assert {h.id for h in active if needs_review(h)} == {h.id for h in active if expected(h)}
