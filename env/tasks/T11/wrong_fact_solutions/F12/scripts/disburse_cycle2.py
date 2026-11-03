"""Ops script: cycle-2 cash disbursement. SENDS PAYMENTS (appends to data/outbox/payments.jsonl).

Built on the wrong F12: recording payments in the audit log is optional.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eligibility.rules import is_eligible  # noqa: E402
from payments.vouchers import disburse, payment_key  # noqa: E402
from registry.register import load_households  # noqa: E402

CYCLE = 2
AMOUNT = 60
ACTOR = "scripts/disburse_cycle2.py"


def main() -> None:
    for household in load_households(active_only=True):
        if is_eligible(household):
            payment = disburse(household.id, AMOUNT, payment_key(household.id, CYCLE))
            print(f"paid {household.id} {AMOUNT} ({payment.id})")


if __name__ == "__main__":
    main()
