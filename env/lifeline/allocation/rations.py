"""How many food kits a household receives in one distribution round."""

import math

from config.settings import region
from config.settings import today as _today
from core.models import Household

# Infants eat much less than older children and adults, so for rations
# a member younger than INFANT_AGE counts as INFANT_WEIGHT of a person.
INFANT_AGE = 2
INFANT_WEIGHT = 0.5

# Every enrolled household receives at least this many kits.
MIN_KITS = 1


def ration_size(household: Household, today=None) -> float:
    """Number of people the household is fed as, e.g. 4 adults + 2 infants -> 5.0."""
    day = today or _today()
    return sum(INFANT_WEIGHT if m.age_on(day) < INFANT_AGE else 1 for m in household.members)


def food_kits(household: Household, today=None) -> int:
    """Kits for one round. Partial kits cannot be handed out, so the count is
    always rounded down (never up: stock is too scarce to round up)."""
    per_kit = region(household.region)["people_per_kit"]
    return max(MIN_KITS, math.floor(ration_size(household, today) / per_kit))
