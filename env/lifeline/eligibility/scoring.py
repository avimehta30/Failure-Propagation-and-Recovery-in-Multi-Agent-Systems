"""Vulnerability score: how badly a household needs help, from 0 to 100 (higher = more need)."""

from config.settings import today as _today
from core.models import Household

POINTS = {
    "child_under_5": 8,        # per child, up to 3 children
    "elder_over_65": 10,       # per elder, up to 2 elders
    "pregnant": 10,
    "disability": 15,
    "shelter_damaged": 20,
    "income_lost": 15,
    "large_household": 10,     # 6 or more members
}


def score_breakdown(household: Household, today=None) -> dict[str, int]:
    day = today or _today()
    ages = [m.age_on(day) for m in household.members]
    parts = {
        "child_under_5": POINTS["child_under_5"] * min(3, sum(a < 5 for a in ages)),
        "elder_over_65": POINTS["elder_over_65"] * min(2, sum(a > 65 for a in ages)),
        "pregnant": POINTS["pregnant"] if any(m.pregnant for m in household.members) else 0,
        "disability": POINTS["disability"] if household.disability else 0,
        "shelter_damaged": POINTS["shelter_damaged"] if household.shelter_damaged else 0,
        "income_lost": POINTS["income_lost"] if household.income_lost else 0,
        "large_household": POINTS["large_household"] if household.size >= 6 else 0,
    }
    return {k: v for k, v in parts.items() if v}


def vulnerability_score(household: Household, today=None) -> int:
    return min(100, sum(score_breakdown(household, today).values()))
