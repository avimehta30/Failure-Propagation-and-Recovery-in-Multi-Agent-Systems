"""Audit trail: the organization's record of who did what, kept for donors and reviewers.

RULE: every payment must be recorded here, straight after it is sent:

    record("payment", actor, ref=payment.id)

`actor` is the person or script responsible (e.g. "scripts/cycle_payments.py").
Donor reports treat a payment with no audit entry as unaccounted-for money.

Other actions worth recording: "registry_merge", "stock_release", "sms_batch".
The log is append-only (data/audit.jsonl); entries are never edited or removed.
"""

from config.settings import now as _now
from core import store

AUDIT = "audit.jsonl"
EVENTS = ("payment", "registry_merge", "stock_release", "sms_batch")


def record(event: str, actor: str, ref: str, *, now=None) -> dict:
    if event not in EVENTS:
        raise ValueError(f"unknown audit event {event!r}; expected one of {EVENTS}")
    if not actor or not ref:
        raise ValueError("audit entries need an actor and a ref")
    entry = {"event": event, "actor": actor, "ref": ref,
             "at": (now or _now()).isoformat(timespec="seconds")}
    store.append_jsonl(AUDIT, entry)
    return entry


def entries(event: str | None = None) -> list[dict]:
    return [e for e in store.read_jsonl(AUDIT) if event is None or e["event"] == event]
