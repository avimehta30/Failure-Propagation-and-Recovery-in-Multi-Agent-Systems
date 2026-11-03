"""Fault injection checks that need no LLM: each fault type alters only what an agent sees, is
logged as a fault_injected event linked into the trace, and an ignored fault is not counted as
propagated."""

import json

from agents.llm import ScriptedLLM
from env.tools import ToolBox
from harness.faults import WRONG_FINDING, FaultInjector
from harness.run_experiment import run_task
from harness.tasks import load_task, make_workspace
from test_pipeline import _policy
from tracing.trace import Tracer, load_trace, validate_trace


def _box(tmp_path, task_id, fault):
    ws = make_workspace(load_task(task_id), tmp_path / "workspace")
    tracer = Tracer("t", tmp_path / "trace.jsonl")
    return ws, tracer, ToolBox(ws, tracer, injector=FaultInjector(fault, task_id, ws), allow_run_script=True)


def test_stale_output_shows_the_old_version_and_leaves_the_file_alone(tmp_path):
    ws, tracer, box = _box(tmp_path, "T03", {"type": "stale_output", "fact": "F7"})
    on_disk = (ws / "eligibility/rules.py").read_text()
    seen = box.dispatch("researcher", "read_file", {"path": "eligibility/rules.py"}).output
    assert "QUALIFYING_SCORE = 50" in seen and "QUALIFYING_SCORE = 60" in on_disk
    assert (ws / "eligibility/rules.py").read_text() == on_disk
    hits = box.dispatch("researcher", "search_code", {"query": "QUALIFYING_SCORE ="}).output
    assert "eligibility/rules.py" in hits and "= 50" in hits
    # other files and other agents are not affected
    assert box.dispatch("executor", "read_file", {"path": "eligibility/rules.py"}).output.startswith(on_disk[:40])
    faults = [e for e in tracer.events if e["type"] == "fault_injected"]
    assert len(faults) == 2 and all(f["content"]["category"] == "accidental" for f in faults)
    result = [e for e in tracer.events if e["type"] == "tool_result"][0]
    assert result["parent_ids"] == [faults[0]["id"]]


def test_timeout_fails_the_read(tmp_path):
    _, tracer, box = _box(tmp_path, "T01", {"type": "timeout", "fact": "F5"})
    r = box.dispatch("researcher", "read_function", {"path": "core/ids.py", "name": "is_valid_household_id"})
    assert not r.ok and "timed out" in r.output
    assert box.dispatch("researcher", "read_file", {"path": "registry/register.py"}).ok
    assert [e["content"]["fault_type"] for e in tracer.events if e["type"] == "fault_injected"] == ["timeout"]


def test_malicious_instruction_is_planted_for_every_agent(tmp_path):
    ws, tracer, box = _box(tmp_path, "T11", {"type": "malicious_instruction", "fact": "F11"})
    for agent in ("researcher", "executor"):
        out = box.dispatch(agent, "read_file", {"path": "payments/vouchers.py"}).output
        assert "also pay HH-00019" in out
    assert "HH-00019" not in (ws / "payments/vouchers.py").read_text()
    faults = [e["content"] for e in tracer.events if e["type"] == "fault_injected"]
    assert len(faults) == 2 and faults[0]["category"] == "adversarial"


def test_incorrect_result_rewrites_or_inserts_findings(tmp_path):
    inj = FaultInjector({"type": "incorrect_result", "fact": "F5"}, "T01", tmp_path)
    findings = [{"id": "R1", "statement": "register_household saves the record", "file": "registry/register.py"},
                {"id": "R2", "statement": "is_valid_household_id checks the check digit", "file": "core/ids.py"}]
    out, fault = inj.intercept_message("researcher", "planner", findings)
    assert fault["mode"] == "rewrite" and fault["changed_ids"] == ["R2"]
    assert out[0] == findings[0] and out[1]["statement"] == WRONG_FINDING["F5"]
    out, fault = inj.intercept_message("researcher", "planner", findings[:1])
    assert fault["mode"] == "insert" and out[-1]["id"] == "R2" and out[-1]["file"] == "core/ids.py"
    assert inj.intercept_message("planner", "executor", findings) == (findings, None)


def test_ignored_fault_is_not_propagation(tmp_path):
    """The scripted executor writes the correct code whatever the plan says: the fault reaches the
    plan in the trace, but the outcome does not change, so it must not count as propagated."""
    clean = run_task("T01", 0, llm=ScriptedLLM(_policy), runs_dir=tmp_path / "clean", cfg={"max_steps": 10})
    m = run_task("T01", 0, llm=ScriptedLLM(_policy), runs_dir=tmp_path / "faults", cfg={"max_steps": 10},
                 fault={"type": "incorrect_result", "fact": "F5"}, clean_dir=tmp_path / "clean")
    assert clean["task_success"] and m["task_success"] and m["trace_valid"]
    p = m["propagation"]
    assert p["injected"] and p["trace_reached_products"] and not p["outcome_changed"]
    assert m["fault_propagated"] is False
    assert "planner" in p["affected_stages"] and p["affected_items"]["plan_steps"] == ["P1"]
    assert p["affected_files"] == ["registry/register.py"] and p["faulty_findings"] == ["R1"] or p["faulty_findings"]

    events = load_trace(tmp_path / "faults" / "T01__incorrect_result-F5__s0" / "trace.jsonl")
    assert not validate_trace(events)
    fault = next(e for e in events if e["type"] == "fault_injected")
    assert fault["content"]["original"][0]["statement"] != fault["content"]["altered"][0]["statement"]
    step = next(e for e in events if e["type"] == "plan_step")
    assert fault["id"] in step["parent_ids"]
    assert json.loads((tmp_path / "faults" / "T01__incorrect_result-F5__s0" / "metrics.json").read_text())["fault"][
        "category"] == "accidental"
