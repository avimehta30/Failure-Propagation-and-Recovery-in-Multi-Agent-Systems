"""End-to-end pipeline check with a scripted (offline) model: researcher -> planner -> executor on T01."""

import json

from agents.llm import ScriptedLLM
from harness.run_experiment import run_task
from harness.tasks import load_task
from tracing.trace import load_trace, validate_trace

REFERENCE = (load_task("T01").reference_solution / "registry" / "register.py").read_text()


def _policy(messages):
    role = messages[0]["content"].split("You are the ")[1].split(" ")[0]
    turn = sum(m["role"] == "assistant" for m in messages)
    if role == "researcher":
        if turn == 0:
            return json.dumps({"tool": "read_function", "args": {"path": "core/ids.py", "name": "is_valid_household_id"}})
        if turn == 1:
            return json.dumps({"tool": "read_file", "args": {"path": "registry/register.py"}})
        return json.dumps({"final": {"findings": [
            {"id": "R1", "statement": "core/ids.py has is_valid_household_id(household_id) -> bool (check digit).",
             "file": "core/ids.py"},
            {"id": "R2", "statement": "register_household(record) saves without checking the ID.",
             "file": "registry/register.py"}]}})
    if role == "planner":
        return json.dumps({"final": {"steps": [
            {"id": "P1", "file": "registry/register.py", "change": "validate the ID", "uses": ["R1", "R2"], "after": []}]}})
    if turn == 0:
        return json.dumps({"tool": "read_file", "args": {"path": "registry/register.py"}})
    if turn == 1:
        return json.dumps({"tool": "write_file", "args": {"path": "registry/register.py", "content": REFERENCE, "step": "P1"}})
    return json.dumps({"final": {"summary": "added the check", "done_steps": ["P1"]}})


def test_scripted_run_solves_t01_with_a_branching_trace(tmp_path):
    m = run_task("T01", 0, llm=ScriptedLLM(_policy), runs_dir=tmp_path, cfg={"max_steps": 10})
    assert m["task_success"] and m["trace_valid"], m
    assert m["findings"] == 2 and m["plan_steps"] == 1 and m["file_edits"] == ["registry/register.py"]
    assert m["unauthorized_actions"]["count"] == 0

    events = load_trace(tmp_path / "T01__clean__s0" / "trace.jsonl")
    assert not validate_trace(events)
    by_type = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)
    findings = {e["content"]["id"]: e["id"] for e in by_type["finding"]}
    step = by_type["plan_step"][0]
    edit = by_type["file_edit"][0]
    assert set(step["parent_ids"]) == {findings["R1"], findings["R2"]}          # P1 <- R1, R2

    def ancestors(eid):
        idx = {e["id"]: e for e in events}
        seen, todo = set(), list(idx[eid]["parent_ids"])
        while todo:
            i = todo.pop()
            if i not in seen:
                seen.add(i)
                todo.extend(idx[i]["parent_ids"])
        return seen
    assert {step["id"], findings["R1"], findings["R2"]} <= ancestors(edit["id"])  # R -> P1 -> E1
    # R1 came from reading core/ids.py, not from the read of register.py
    r1 = next(e for e in by_type["finding"] if e["content"]["id"] == "R1")
    sources = [next(x for x in events if x["id"] == p) for p in r1["parent_ids"]]
    assert all(s["type"] == "tool_result" and "is_valid_household_id" in s["content"]["output"] for s in sources)


def test_agent_recovers_from_bad_json_and_bad_plan(tmp_path):
    state = {"planner_tries": 0}

    def policy(messages):
        role = messages[0]["content"].split("You are the ")[1].split(" ")[0]
        if role == "planner":
            state["planner_tries"] += 1
            if state["planner_tries"] == 1:
                return "Sure! Here is my plan: step one..."                          # not JSON
            if state["planner_tries"] == 2:
                return json.dumps({"final": {"steps": [{"id": "P1", "file": "x.py", "change": "y", "uses": ["R9"]}]}})
        return _policy(messages)

    m = run_task("T01", 0, llm=ScriptedLLM(policy), runs_dir=tmp_path, cfg={"max_steps": 10})
    assert m["task_success"] and m["agents"]["planner"]["steps"] == 3
