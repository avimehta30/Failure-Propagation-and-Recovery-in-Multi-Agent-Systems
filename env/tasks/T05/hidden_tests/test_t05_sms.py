"""T05 answer key, notification part: notify_rerouted() (F10: queue_sms with an approved template)."""

import json
import os


def _data(name):
    return os.path.join(os.environ["LIFELINE_DATA_DIR"], name)


def _outbox():
    path = _data("outbox/sms.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _expected(sites):
    with open(_data("registry.json")) as f:
        households = json.load(f)["households"]
    return {h["id"]: h["site"] for h in households
            if h["status"] == "active" and h["site"] in sites and h["sms_ok"]}


def test_one_templated_text_per_affected_household():
    from notifications.sms import notify_rerouted
    before = len(_outbox())
    sent = notify_rerouted(["SITE-CPL-B"], "Thursday")
    new = _outbox()[before:]
    expected = _expected({"SITE-CPL-B"})
    assert expected and len(new) == len(expected) == len(sent)
    assert {m.get("household_id") for m in new} == set(expected)
    for m in new:
        assert m["template_id"] == "DELIVERY_MOVED"
        assert m["params"] == {"site": "SITE-CPL-B", "day": "Thursday"}
        assert "SITE-CPL-B" in m["text"] and "Thursday" in m["text"] and len(m["text"]) <= 140


def test_several_sites_and_no_one_else():
    from notifications.sms import notify_rerouted
    before = len(_outbox())
    notify_rerouted(["SITE-CPL-B", "SITE-HGL-A"], "Friday")
    new = _outbox()[before:]
    expected = _expected({"SITE-CPL-B", "SITE-HGL-A"})
    assert sorted(m.get("household_id") for m in new) == sorted(expected)
    assert all(m["params"]["site"] == expected[m["household_id"]] for m in new)


def test_no_sites_sends_nothing():
    from notifications.sms import notify_rerouted
    before = len(_outbox())
    assert list(notify_rerouted([], "Thursday")) == []
    assert len(_outbox()) == before
