"""How many food kits a household receives in one distribution round."""

import math

from config.settings import region
from config.settings import today as _today
from core.models import Household

# Infants eat much less than older children and adults, so for rations
# a member younger than INFANT_AGE counts as INFANT_WEIGHT of a person.
INFANT_AGE = 2
INFANT_WEIGHT = 0.5

# One food kit feeds exactly this many people for a distribution round.
PEOPLE_PER_KIT = 2

# Every enrolled household receives at least this many kits.
MIN_KITS = 1


def ration_size(household: Household, today=None) -> float:
    """Number of people the household is fed as, e.g. 4 adults + 2 infants -> 5.0."""
    day = today or _today()
    return sum(INFANT_WEIGHT if m.age_on(day) < INFANT_AGE else 1 for m in household.members)


def food_kits(household: Household, today=None) -> int:
    """Kits for one round. Partial kits cannot be handed out, so the count is
    always rounded down (never up: stock is too scarce to round up)."""
    return max(MIN_KITS, math.floor(ration_size(household, today) / PEOPLE_PER_KIT))


def winter_kits(household: Household, today=None) -> int:
    """Winter kits for one round: only in regions with a winter_kit setting, counted with the
    same household-size rules as food kits, and at least one per household."""
    setting = region(household.region).get("winter_kit")
    if not setting:
        return 0
    return max(MIN_KITS, math.floor(ration_size(household, today) / setting["people_per_kit"]))
