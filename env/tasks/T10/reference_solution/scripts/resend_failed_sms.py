"""Ops script: re-send cycle-1 texts that failed. SENDS SMS (appends to data/outbox/sms.jsonl).

Run once from the Lifeline root:  python scripts/resend_failed_sms.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notifications.sms import delivery_status, queue_sms, sent_messages  # noqa: E402


def main() -> None:
    failed = {sms_id for sms_id, status in delivery_status().items() if status == "failed"}
    for message in sent_messages():
        if message.id in failed:
            new = queue_sms(message.household_id, message.template_id, message.params)
            print(f"re-sent {message.id} to {message.household_id} as {new.id}")


if __name__ == "__main__":
    main()
