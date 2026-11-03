"""Who qualifies for help, and for which programs (food, cash, shelter)."""

from core.models import Household
from eligibility.scoring import vulnerability_score

# A household qualifies when its vulnerability score reaches the threshold.
# Pregnancy carries extra health risk, so those households qualify earlier.
QUALIFYING_SCORE = 60
PREGNANCY_QUALIFYING_SCORE = 45

# Households this many points or fewer below their cutoff are flagged for a caseworker.
REVIEW_MARGIN = 5


def has_pregnant_member(household: Household) -> bool:
    return any(m.pregnant for m in household.members)


def threshold_for(household: Household) -> int:
    return PREGNANCY_QUALIFYING_SCORE if has_pregnant_member(household) else QUALIFYING_SCORE


def is_eligible(household: Household, score: int | None = None, today=None) -> bool:
    if household.status != "active":
        return False
    score = vulnerability_score(household, today) if score is None else score
    return score >= threshold_for(household)


def programs(household: Household, today=None) -> list[str]:
    """Programs the household is enrolled in. Eligible households get food and cash;
    those whose shelter was damaged also get shelter materials."""
    if not is_eligible(household, today=today):
        return []
    result = ["food", "cash"]
    if household.shelter_damaged:
        result.append("shelter")
    return result


def needs_review(household: Household, today=None) -> bool:
    """True for an active household that does not qualify yet but is within REVIEW_MARGIN points."""
    if household.status != "active":
        return False
    cutoff = threshold_for(household)
    return cutoff - REVIEW_MARGIN <= vulnerability_score(household, today) < cutoff
