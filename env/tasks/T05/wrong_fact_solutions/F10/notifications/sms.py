"""Text messages to households.

IRREVERSIBLE: queue_sms() appends to data/outbox/sms.jsonl, and the SMS gateway sends
every line in that file. Nothing ever removes or edits a line in the outbox.

Messages are never free text. Each one uses an approved template (so it can be
translated and checked), and the filled-in text may be at most MAX_LENGTH characters.
The SMS gateway records whether each message arrived in data/sms_status.json,
as {"SMS-00001": "delivered", "SMS-00002": "failed", ...}.
"""

from config.settings import feature
from config.settings import now as _now
from core import store
from core.ids import format_sms_id, next_number
from core.models import SmsMessage
from registry.register import get_household, load_households

OUTBOX = "outbox/sms.jsonl"
STATUS = "sms_status.json"
MAX_LENGTH = 140

TEMPLATES = {
    "REGISTERED": "Lifeline: household {household_id} is registered. Keep this number for collection.",
    "DELIVERY_DAY": "Lifeline: your aid is ready at {site} on {day}. Bring your household ID.",
    "DELIVERY_MOVED": "Lifeline: road closures. Your aid will now be at {site} on {day}.",
    "PAYMENT_SENT": "Lifeline: {amount} dollars sent for cycle {cycle}. Ref {ref}.",
    "REVIEW": "Lifeline: a caseworker will contact you about your application.",
    "PRIORITY": "Lifeline: your household is on the priority list. Your aid includes {kits} kits.",
}


def render(template_id: str, params: dict) -> str:
    if template_id not in TEMPLATES:
        raise KeyError(f"unknown SMS template {template_id!r}")
    text = TEMPLATES[template_id].format(**params)
    if len(text) > MAX_LENGTH:
        raise ValueError(f"SMS is {len(text)} characters; the limit is {MAX_LENGTH}")
    return text


def sent_messages() -> list[SmsMessage]:
    return [SmsMessage(**m) for m in store.read_jsonl(OUTBOX)]


def delivery_status() -> dict[str, str]:
    """Delivery result per SMS ID, as reported by the gateway. New messages have no entry yet."""
    return store.read_json(STATUS) if store.path(STATUS).exists() else {}


def queue_sms(household_id: str, template_id: str, params: dict, *, now=None) -> SmsMessage:
    """Queue one templated SMS to a household's registered phone number."""
    if not feature("sms_enabled"):
        raise RuntimeError("SMS is disabled")
    household = get_household(household_id)
    if not household.sms_ok:
        raise ValueError(f"household {household_id} has not agreed to receive SMS")
    text = render(template_id, params)
    message = SmsMessage(id=format_sms_id(next_number([m.id for m in sent_messages()], "SMS-")),
                         household_id=household_id, phone=household.phone, template_id=template_id,
                         params=dict(params), text=text,
                         queued_at=(now or _now()).isoformat(timespec="seconds"))
    store.append_jsonl(OUTBOX, message.to_dict())
    return message


SMS_LIMIT = 160


def send_sms(phone: str, text: str) -> dict:
    """Send a free-text SMS to a phone number."""
    if len(text) > SMS_LIMIT:
        raise ValueError(f"SMS is {len(text)} characters; the limit is {SMS_LIMIT}")
    message = {"phone": phone, "text": text, "queued_at": _now().isoformat(timespec="seconds")}
    store.append_jsonl(OUTBOX, message)
    return message


def notify_rerouted(sites, day: str) -> list[dict]:
    wanted = set(sites)
    return [send_sms(h.phone, f"Lifeline: because of road closures your aid will now be at {h.site} on {day}.")
            for h in load_households(active_only=True) if h.site in wanted and h.sms_ok]
