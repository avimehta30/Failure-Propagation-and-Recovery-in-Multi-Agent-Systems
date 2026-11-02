"""ID formats used across Lifeline.

    Household    HH-NNNNC     four digits, then one check digit (see household_check_digit)
    Warehouse    WH-RRR-NN    region code, then a two-digit number
    Lot          LOT-NNNN
    Reservation  RSV-NNNN
    Payment      PAY-NNNNN
    SMS          SMS-NNNNN
"""

import re

from config.settings import region_codes

# Weights for the household check digit, applied to the four base digits in order.
CHECK_WEIGHTS = (6, 8, 10, 12)


def household_check_digit(base: str) -> int | None:
    """Mod-11 check digit for the four-digit base of a household ID.

    Returns None when the result would be 10. Bases like that are never issued.
    """
    if len(base) != 4 or not base.isdigit():
        raise ValueError(f"household ID base must be 4 digits, got {base!r}")
    total = sum(int(d) * w for d, w in zip(base, CHECK_WEIGHTS))
    check = (11 - total % 11) % 11
    return None if check == 10 else check


def make_household_id(number: int) -> str:
    base = f"{number:04d}"
    check = household_check_digit(base)
    if check is None:
        raise ValueError(f"base {base} has no valid check digit; use the next number")
    return f"HH-{base}{check}"


def format_warehouse_id(region: str, number: int) -> str:
    if region not in region_codes():
        raise ValueError(f"unknown region {region!r}")
    if not 1 <= number <= 99:
        raise ValueError("warehouse number must be 1-99")
    return f"WH-{region}-{number:02d}"


def format_lot_id(number: int) -> str:
    return f"LOT-{number:04d}"


def format_reservation_id(number: int) -> str:
    return f"RSV-{number:04d}"


def format_payment_id(number: int) -> str:
    return f"PAY-{number:05d}"


def format_sms_id(number: int) -> str:
    return f"SMS-{number:05d}"


def next_number(existing_ids, prefix: str) -> int:
    """1 + the highest number used so far with this prefix (e.g. 'PAY-')."""
    numbers = [int(m.group(1)) for i in existing_ids
               if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", i))]
    return max(numbers, default=0) + 1
