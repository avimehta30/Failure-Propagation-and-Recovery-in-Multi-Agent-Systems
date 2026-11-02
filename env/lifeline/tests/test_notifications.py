import pytest

from notifications.sms import MAX_LENGTH, TEMPLATES, queue_sms, render, sent_messages
from registry.register import load_households


def test_templates_fit_the_limit():
    assert MAX_LENGTH == 140
    assert render("DELIVERY_DAY", {"site": "SITE-NVL-A", "day": "Tuesday"}).startswith("Lifeline:")


def test_too_long_is_rejected():
    with pytest.raises(ValueError):
        render("DELIVERY_DAY", {"site": "X" * 120, "day": "Tuesday"})


def test_unknown_template_is_rejected():
    with pytest.raises(KeyError):
        render("FREE_TEXT", {})


def test_queue_sms_uses_registered_phone():
    h = next(h for h in load_households(active_only=True) if h.sms_ok)
    before = len(sent_messages())
    m = queue_sms(h.id, "REVIEW", {})
    assert len(sent_messages()) == before + 1
    assert m.phone == h.phone and m.text == TEMPLATES["REVIEW"] and m.delivery == "pending"


def test_opted_out_households_get_no_sms():
    h = next(h for h in load_households() if not h.sms_ok)
    with pytest.raises(ValueError):
        queue_sms(h.id, "REVIEW", {})


def test_seed_outbox_has_failed_messages():
    assert any(m.delivery == "failed" for m in sent_messages())
