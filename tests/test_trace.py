import pytest

from tracing.trace import Tracer, load_trace, validate_trace


def _chain(tmp_path):
    t = Tracer("run-1", tmp_path / "trace.jsonl")
    ticket = t.log("harness", "message", {"task_input": True, "text": "ticket"})
    r1 = t.log("researcher", "finding", {"id": "R1"}, [ticket["id"]])
    r2 = t.log("researcher", "finding", {"id": "R2"}, [ticket["id"]])
    p1 = t.log("planner", "plan_step", {"id": "P1"}, [r1["id"]])
    p2 = t.log("planner", "plan_step", {"id": "P2"}, [r1["id"], r2["id"]])
    p3 = t.log("planner", "plan_step", {"id": "P3"}, [p2["id"]])          # a step depending on a step
    e2 = t.log("executor", "file_edit", {"path": "a.py"}, [p2["id"]])
    return t, dict(ticket=ticket, r1=r1, r2=r2, p1=p1, p2=p2, p3=p3, e2=e2)


def test_event_fields_and_ids(tmp_path):
    t, ev = _chain(tmp_path)
    e = ev["r1"]
    assert e["id"] == "e0002" and e["run_id"] == "run-1"
    assert set(e) == {"id", "parent_ids", "run_id", "timestamp", "agent", "type", "content",
                      "tokens_in", "tokens_out", "latency_ms"}


def test_chains_branch(tmp_path):
    t, ev = _chain(tmp_path)
    # R2 taints P2, P3 and E2, but not P1
    assert t.descendants(ev["r2"]["id"]) == {ev["p2"]["id"], ev["p3"]["id"], ev["e2"]["id"]}
    assert ev["p1"]["id"] not in t.descendants(ev["r2"]["id"])
    assert t.ancestors(ev["e2"]["id"]) == {ev["p2"]["id"], ev["r1"]["id"], ev["r2"]["id"], ev["ticket"]["id"]}


def test_written_to_disk_and_valid(tmp_path):
    t, _ = _chain(tmp_path)
    events = load_trace(tmp_path / "trace.jsonl")
    assert events == t.events and validate_trace(events) == []


def test_validation_catches_problems():
    events = [{"id": "e0001", "parent_ids": [], "type": "finding", "content": {}},
              {"id": "e0002", "parent_ids": ["e0009"], "type": "plan_step", "content": {}},
              {"id": "e0003", "parent_ids": ["e0001"], "type": "nonsense", "content": {}}]
    problems = validate_trace(events)
    assert any("no parents" in p for p in problems)
    assert any("unknown or comes later" in p for p in problems)
    assert any("unknown type" in p for p in problems)


def test_logging_rejects_unknown_parents_and_types():
    t = Tracer("x")
    with pytest.raises(ValueError):
        t.log("a", "finding", {}, ["e0042"])
    with pytest.raises(ValueError):
        t.log("a", "gossip", {})
