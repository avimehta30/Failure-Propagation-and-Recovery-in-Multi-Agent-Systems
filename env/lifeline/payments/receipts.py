"""Payment receipts for caseworkers and households."""

from core.models import Payment
from payments.vouchers import sent_payments


def receipt_text(payment: Payment) -> str:
    return (f"Receipt {payment.id}: {payment.amount} dollars to {payment.household_id} "
            f"on {payment.sent_at[:10]}")


def receipts_for(household_id: str) -> list[str]:
    return [receipt_text(p) for p in sent_payments() if p.household_id == household_id]


def total_paid(household_id: str | None = None) -> int:
    return sum(p.amount for p in sent_payments() if household_id in (None, p.household_id))
