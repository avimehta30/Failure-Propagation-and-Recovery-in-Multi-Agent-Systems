"""The outbox guard only reads records. It reports sends a restart would repeat."""

import json
from pathlib import Path

from harness.outbox_guard import already_sent, classify_restart, guard_report, read_jsonl, sends_to_skip


def _sms(household, template="DELIVERY_DAY", **params):
    return {"id": f"SMS-{household}", "household_id": household, "template_id": template,
            "params": params or {"site": "site-a", "day": "Friday"}}


def _payment(household, amount=4000, cycle=1):
    return {"id": f"PAY-{household}", "household_id": household, "amount": amount,
            "key": f"{household}:{cycle}"}


def test_already_sent_matches_sms_and_payment_keys():
    sent = [_sms("HH-10421", site="site-a", day="Friday")]
    same = _sms("HH-10421", site="site-a", day="Friday")
    same["id"] = "SMS-other"
    same["params"] = {"day": "Friday", "site": "site-a"}
    assert already_sent(sent, same, "sms")
    assert not already_sent(sent, _sms("HH-10421", template="REVIEW"), "sms")
    assert not already_sent(sent, _sms("HH-00019", site="site-a", day="Friday"), "sms")

    paid = [_payment("HH-10421")]
    assert already_sent(paid, _payment("HH-10421"), "payment")
    assert not already_sent(paid, _payment("HH-10421", amount=5000), "payments")
    assert sent == [_sms("HH-10421", site="site-a", day="Friday")]


def test_later_copy_of_a_new_send_is_skipped_too():
    first = _sms("HH-20001", site="site-b", day="Monday")
    second = _sms("HH-20001", site="site-b", day="Monday")
    skipped = sends_to_skip([], [first, second, _sms("HH-20002", site="site-b", day="Monday")], "outbox/sms.jsonl")
    assert skipped == [second]


def test_classify_restart_counts_only_repeats_of_the_copied_prefix():
    prefix = [_sms("HH-10421"), _payment("HH-10421")]
    added_sms = [_sms("HH-10421"), _sms("HH-30003", template="REVIEW", site="site-c")]
    sms = classify_restart(prefix[:1], prefix[:1] + added_sms, "outbox/sms.jsonl")
    assert sms["prefix_intact"] and sms["added"] == 2 and sms["would_block"] == 1
    pay = classify_restart(prefix[1:], prefix[1:] + [_payment("HH-30003")], "outbox/payments.jsonl")
    assert pay["would_block"] == 0
    broken = classify_restart(prefix[:1], [_sms("HH-99999")] + added_sms, "sms")
    assert not broken["prefix_intact"] and broken["would_block"] is None


def test_read_jsonl_leaves_the_file_unchanged(tmp_path):
    path = tmp_path / "sms.jsonl"
    original = json.dumps(_sms("HH-10421")) + "\n" + "not-json\n"
    path.write_text(original)
    rows = read_jsonl(path)
    assert rows[0]["household_id"] == "HH-10421" and rows[1] == {"_unparsed": "not-json"}
    assert path.read_text() == original
    assert read_jsonl(tmp_path / "missing.jsonl") == []


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_report_scans_full_restart_runs_without_writing(tmp_path):
    prefix = [_sms("HH-10421"), _sms("HH-10422", template="REVIEW")]
    added = [_sms("HH-10421"), _sms("HH-50005")]
    faulty = "T10__incorrect_result-F10__s0"
    fault_run = tmp_path / "faults" / faulty
    recovery = tmp_path / "recovery" / f"{faulty}__full_restart"
    _write_jsonl(fault_run / "workspace" / "data" / "outbox" / "sms.jsonl", prefix)
    _write_jsonl(recovery / "workspace" / "data" / "outbox" / "sms.jsonl", prefix + added)
    (recovery / "metrics.json").write_text(json.dumps({
        "task_id": "T10", "seed": 0, "run_name": f"{faulty}__full_restart",
        "recovery": {"faulty_run": faulty, "method": "full_restart"},
    }))
    before = (recovery / "workspace" / "data" / "outbox" / "sms.jsonl").read_text()

    rows = guard_report(tmp_path / "recovery")
    assert len(rows) == 1
    sms = rows[0]["outboxes"]["outbox/sms.jsonl"]
    assert rows[0]["fault_run_found"] and sms["would_block"] == 1 and sms["added"] == 2
    assert rows[0]["outboxes"]["outbox/payments.jsonl"]["would_block"] == 0
    assert (recovery / "workspace" / "data" / "outbox" / "sms.jsonl").read_text() == before
