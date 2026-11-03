"""Full-restart baseline checks with a scripted (offline) model."""

import json

from agents.llm import ScriptedLLM
from harness.recovery import full_restart
from harness.run_experiment import run_task
from test_pipeline import _policy

CFG = {"max_steps": 10}


def test_full_restart_reruns_everything_and_keeps_what_was_sent(tmp_path):
    run_task("T01", 0, llm=ScriptedLLM(_policy), runs_dir=tmp_path / "clean", cfg=CFG)
    run_task("T01", 0, llm=ScriptedLLM(_policy), runs_dir=tmp_path / "faults", cfg=CFG,
             fault={"type": "incorrect_result", "fact": "F5"}, clean_dir=tmp_path / "clean")
    faulty = tmp_path / "faults" / "T01__incorrect_result-F5__s0"
    # Pretend the faulty run had sent a text: it must survive the restart.
    sent = {"id": "SMS-09999", "household_id": "HH-10421", "template_id": "REVIEW", "params": {}}
    with open(faulty / "workspace" / "data" / "outbox" / "sms.jsonl", "a") as f:
        f.write(json.dumps(sent) + "\n")

    m = full_restart(faulty, cfg=CFG, llm=ScriptedLLM(_policy), runs_dir=tmp_path / "recovery")
    r = m["recovery"]
    assert m["method"] == "full_restart" and r["recovered_success"] and m["trace_valid"]
    assert r["recomputed_stages"] == ["researcher", "planner", "executor"] and r["retained_items"] == 0
    assert r["given_faulty_event_ids"] and r["recovery_tokens"] > 0
    outbox = (tmp_path / "recovery" / m["run_name"] / "workspace" / "data" / "outbox" / "sms.jsonl").read_text()
    assert "SMS-09999" in outbox
    # The restart itself had no fault.
    trace = (tmp_path / "recovery" / m["run_name"] / "trace.jsonl").read_text()
    assert "fault_injected" not in trace


def test_always_verify_catches_a_wrong_finding_and_records_its_cost(tmp_path):
    from harness.faults import WRONG_FINDING
    from harness.recovery import always_verify

    def policy(messages):
        role = messages[0]["content"].split("You are the ")[1].split(" ")[0]
        if role == "verifier":
            item = messages[1]["content"]
            if sum(m["role"] == "assistant" for m in messages) == 0:
                return json.dumps({"tool": "read_file", "args": {"path": "core/ids.py"}})
            bad = WRONG_FINDING["F5"][:40] in item
            return json.dumps({"final": {"verdict": "reject" if bad else "accept",
                                         "reason": "core/ids.py has a weighted check digit" if bad else "ok"}})
        return _policy(messages)

    run_task("T01", 0, llm=ScriptedLLM(_policy), runs_dir=tmp_path / "clean", cfg=CFG)
    run_task("T01", 0, llm=ScriptedLLM(_policy), runs_dir=tmp_path / "faults", cfg=CFG,
             fault={"type": "incorrect_result", "fact": "F5"}, clean_dir=tmp_path / "clean")
    m = always_verify(tmp_path / "faults" / "T01__incorrect_result-F5__s0", cfg=CFG, llm=ScriptedLLM(policy),
                      runs_dir=tmp_path / "recovery")
    r = m["recovery"]
    assert m["method"] == "always_verify" and m["trace_valid"] and r["recovered_success"]
    assert r["caught_fault"] and r["items_rejected"] == 1 and r["false_rejections"] == 0 and r["items_redone"] == 1
    assert r["items_checked"] >= 4                 # 2 findings + 1 plan step + 1 edit
    assert r["verifier_tokens"] > 0 and r["verifier_tokens"] < r["recovery_tokens"]
    events = [json.loads(l) for l in open(tmp_path / "recovery" / m["run_name"] / "trace.jsonl")]
    redone = [e for e in events if e["type"] == "finding" and e["content"].get("redone")]
    assert len(redone) == 1 and WRONG_FINDING["F5"] != redone[0]["content"]["statement"]
