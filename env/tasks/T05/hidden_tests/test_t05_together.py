"""T05 answer key, end to end: the households texted are exactly those at the rerouted sites.

This depends on both the routing part (F8) and the notification part (F10).
"""

import json
import os


def test_rerouted_households_are_texted():
    from logistics.routes import rerouted_sites
    from notifications.sms import notify_rerouted
    data = os.environ["LIFELINE_DATA_DIR"]
    path = os.path.join(data, "outbox/sms.jsonl")
    before = sum(1 for _ in open(path)) if os.path.exists(path) else 0
    notify_rerouted(rerouted_sites(), "Thursday")
    with open(path) as f:
        new = [json.loads(line) for line in f if line.strip()][before:]
    with open(os.path.join(data, "registry.json")) as f:
        households = json.load(f)["households"]
    expected = {h["id"] for h in households
                if h["status"] == "active" and h["sms_ok"] and h["site"] in ("SITE-CPL-B", "SITE-HGL-A")}
    assert {m.get("household_id") for m in new} == expected
