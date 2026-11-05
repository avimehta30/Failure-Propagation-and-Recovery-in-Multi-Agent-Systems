"""Identity of a sent text or payment. Grading and the outbox guard both use these.

A text matches when the household, template, and parameters match. A payment matches
when the household, amount, and key match. Generated ids and field order do not matter.
"""

from __future__ import annotations

import json


def sms_key(message: dict):
    return (message.get("household_id"), message.get("template_id"),
            json.dumps(message.get("params"), sort_keys=True))


def payment_key(payment: dict):
    return (payment.get("household_id"), payment.get("amount"), payment.get("key"))


KEYS = {"outbox/sms.jsonl": sms_key, "outbox/payments.jsonl": payment_key}
