"""Cash transfers to households.

IRREVERSIBLE: disburse() appends to data/outbox/payments.jsonl, and a line there is money
that has been sent. Nothing ever removes or edits a line in the outbox.

Each payment carries an idempotency key, "{household_id}:{cycle}" (see payment_key).
A second payment with a key that was already used is rejected, so a script that runs
twice cannot pay a family twice in the same cycle.
"""

from config.settings import feature
from config.settings import now as _now
from core import store
from core.ids import format_payment_id, next_number
from core.models import Payment
from registry.register import get_household

OUTBOX = "outbox/payments.jsonl"


class DuplicatePayment(Exception):
    pass


def payment_key(household_id: str, cycle: int) -> str:
    return f"{household_id}:{cycle}"


def sent_payments() -> list[Payment]:
    return [Payment(**p) for p in store.read_jsonl(OUTBOX)]


def disburse(household_id: str, amount: int, key: str, *, now=None) -> Payment:
    """Send `amount` dollars to a household. Raises DuplicatePayment if `key` was used before."""
    if not feature("cash_enabled"):
        raise RuntimeError("cash transfers are disabled")
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError("amount must be a positive whole number of dollars")
    household = get_household(household_id)
    if household.status != "active":
        raise ValueError(f"household {household_id} is {household.status}")
    sent = sent_payments()
    if any(p.key == key for p in sent):
        raise DuplicatePayment(f"a payment with key {key!r} was already sent")

    payment = Payment(id=format_payment_id(next_number([p.id for p in sent], "PAY-")),
                      household_id=household_id, amount=amount, key=key,
                      sent_at=(now or _now()).isoformat(timespec="seconds"))
    store.append_jsonl(OUTBOX, payment.to_dict())
    return payment
