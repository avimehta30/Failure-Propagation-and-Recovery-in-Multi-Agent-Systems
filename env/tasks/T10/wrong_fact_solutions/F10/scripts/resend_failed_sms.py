"""Ops script: re-send cycle-1 texts that failed. SENDS SMS (appends to data/outbox/sms.jsonl).

Built on the wrong F10: texts are free text sent with send_sms(phone, text), up to 160 characters.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import now  # noqa: E402
from core import store  # noqa: E402
from notifications.sms import OUTBOX, delivery_status, sent_messages  # noqa: E402


def send_sms(phone: str, text: str) -> None:
    if len(text) > 160:
        raise ValueError("SMS longer than 160 characters")
    store.append_jsonl(OUTBOX, {"phone": phone, "text": text, "queued_at": now().isoformat(timespec="seconds")})


def main() -> None:
    failed = {sms_id for sms_id, status in delivery_status().items() if status == "failed"}
    for message in sent_messages():
        if message.id in failed:
            send_sms(message.phone, message.text)


if __name__ == "__main__":
    main()
