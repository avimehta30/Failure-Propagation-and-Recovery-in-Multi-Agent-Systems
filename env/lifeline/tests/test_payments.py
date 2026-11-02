import pytest

import audit
from payments.receipts import receipts_for, total_paid
from payments.vouchers import DuplicatePayment, disburse, payment_key, sent_payments
from registry.register import load_households


def test_payment_key_format():
    assert payment_key("HH-10427", 2) == "HH-10427:2"


def test_disburse_appends_to_outbox():
    hid = next(h.id for h in load_households(active_only=True))
    before = len(sent_payments())
    p = disburse(hid, 40, payment_key(hid, 9))
    assert len(sent_payments()) == before + 1 and p.id.startswith("PAY-")
    assert receipts_for(hid)[-1].startswith(f"Receipt {p.id}")


def test_same_key_cannot_pay_twice():
    hid = next(h.id for h in load_households(active_only=True))
    disburse(hid, 40, payment_key(hid, 9))
    with pytest.raises(DuplicatePayment):
        disburse(hid, 40, payment_key(hid, 9))


def test_disburse_rejects_bad_amounts_and_inactive():
    hid = next(h.id for h in load_households(active_only=True))
    with pytest.raises(ValueError):
        disburse(hid, 0, payment_key(hid, 9))
    inactive = next(h.id for h in load_households() if h.status == "inactive")
    with pytest.raises(ValueError):
        disburse(inactive, 40, payment_key(inactive, 9))


def test_seed_payments_are_keyed_and_audited():
    payments = sent_payments()
    assert payments and all(p.key == payment_key(p.household_id, 1) for p in payments)
    audited = {e["ref"] for e in audit.entries("payment")}
    assert {p.id for p in payments} <= audited
    assert total_paid() == sum(p.amount for p in payments)


def test_audit_record():
    entry = audit.record("payment", "tests", "PAY-99999")
    assert audit.entries("payment")[-1] == entry
    with pytest.raises(ValueError):
        audit.record("coffee", "tests", "x")
