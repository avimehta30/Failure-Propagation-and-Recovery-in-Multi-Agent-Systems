"""The proctor: runs a task through the agents, grades it, and files the result.

    python -m harness.run_experiment --task T01 --seed 0          # one clean run
    python -m harness.run_experiment --task T01 --seed 0 --force  # redo it (LLM replies still cached)
    python -m harness.run_experiment --task T01 --model api-glm-5.3 --runs-dir runs/pilot_glm
    python -m harness.run_experiment --task T04 --seed 1 --fault incorrect_result:F2 --runs-dir runs/faults

Each run writes runs/<run_name>/{workspace/, trace.jsonl, metrics.json}. A fault run is compared
with the clean run of the same task and seed (in --clean-dir) to decide whether the fault
propagated (harness/propagation.py). The recovery baselines are in harness/recovery.py.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import yaml

from agents.llm import LLM, RateLimitExhausted
from agents.orchestrator import Orchestrator
from env.tools import ToolBox
from harness.faults import CATEGORY, FaultInjector
from harness.grading import run_hidden_tests
from harness.ops import grade_ops
from harness.propagation import analyze
from harness.tasks import ROOT, load_task, make_workspace
from tracing.trace import Tracer, validate_trace

RUNS = ROOT / "runs"
CLEAN = RUNS / "baseline"
CONFIG = ROOT / "harness" / "configs" / "phase1.yaml"


def run_name_for(task_id: str, seed: int, fault: dict | None = None) -> str:
    return f"{task_id}__{fault['type']}-{fault['fact']}__s{seed}" if fault else f"{task_id}__clean__s{seed}"


def run_task(task_id: str, seed: int = 0, *, cfg: dict | None = None, llm=None, run_name: str | None = None,
             runs_dir: Path = RUNS, force: bool = False, fault: dict | None = None, clean_dir: Path = CLEAN,
             prepare=None, method: str = "none", verify: bool = False, no_reading: bool = False) -> dict:
    """One run. `prepare(workspace)` may adjust the fresh workspace before the agents start (the
    recovery baselines use it to carry over what a faulty run already sent)."""
    cfg = cfg or yaml.safe_load(CONFIG.read_text())
    task = load_task(task_id)
    run_name = run_name or (f"{task_id}__noread__s{seed}" if no_reading else run_name_for(task_id, seed, fault))
    run_dir = Path(runs_dir) / run_name
    if (run_dir / "metrics.json").exists() and not force:
        return json.loads((run_dir / "metrics.json").read_text())
    if run_dir.exists():
        shutil.rmtree(run_dir)
    llm = llm or LLM(**cfg["llm"])
    ops = task.meta["kind"] == "ops"
    workspace = make_workspace(task, run_dir / "workspace", seed=seed)
    if prepare:
        prepare(workspace)
    tracer = Tracer(run_name, run_dir / "trace.jsonl")
    injector = FaultInjector(fault, task_id, workspace) if fault else None
    # No-reading test: agents may list folders but not read any file.
    permissions = ({"researcher": {"list_dir"}, "planner": set(), "executor": {"list_dir", "write_file", "run_script"}}
                   if no_reading else None)
    tools = ToolBox(workspace, tracer, injector=injector, allow_run_script=ops, permissions=permissions,
                    allow_visible_tests=cfg.get("run_visible_tests", False))
    tools.hide_script_output = no_reading

    start = time.perf_counter()
    result = Orchestrator(task_id, task.prompt, llm, tools, tracer, injector=injector,
                          max_steps=cfg.get("max_steps", 10), seed=seed, ops=ops,
                          keep_full_results=cfg.get("keep_full_results", 2), verify=verify,
                          verifier_steps=cfg.get("verifier_steps", 6)).run()
    grade = grade_ops(task, workspace, seed) if ops else run_hidden_tests(task, workspace)
    edits = [e["id"] for e in tracer.of_type("file_edit", "executor")]
    tracer.log("harness", "test_result", {k: grade[k] for k in ("passed", "test_results", "n_passed", "n_failed")},
               edits or [result.runs["executor"].final_llm_id or result.task_input_id])
    wall_ms = (time.perf_counter() - start) * 1000

    m = metrics(task, seed, run_name, cfg, tracer, result, grade, wall_ms, getattr(llm, "model", None))
    m["method"] = "no_reading" if no_reading else method
    if result.verification is not None:
        v = dict(result.verification)
        v["verifier_tokens"] = v["tokens_in"] + v["tokens_out"]
        m["verification"] = v
    if fault:
        clean_path = Path(clean_dir) / run_name_for(task_id, seed) / "metrics.json"
        clean = json.loads(clean_path.read_text()) if clean_path.exists() else None
        m["fault"] = dict(fault, category=CATEGORY[fault["type"]])
        m["clean_run"] = str(clean_path) if clean else None
        m["clean_success"] = clean["task_success"] if clean else None
        m["propagation"] = analyze(task_id, fault, tracer.events, m, clean)
        m["fault_propagated"] = m["propagation"]["fault_propagated"]
    (run_dir / "metrics.json").write_text(json.dumps(m, indent=2))
    return m


def metrics(task, seed, run_name, cfg, tracer, result, grade, wall_ms, model) -> dict:
    llm_calls = tracer.of_type("llm_call")
    unauthorized = [e["content"] for e in tracer.of_type("unauthorized_action")]
    per_agent = {name: {"steps": r.steps, "exhausted": r.exhausted, "tokens_in": r.tokens_in,
                        "tokens_out": r.tokens_out, "llm_latency_ms": round(r.latency_ms, 1),
                        "tool_calls": len(r.tool_uses)} for name, r in result.runs.items()}
    problems = validate_trace(tracer.events)
    return {
        "run_name": run_name, "task_id": task.id, "tier": task.meta["tier"], "seed": seed, "fault": None,
        "method": "none", "model": model,
        "task_success": grade["passed"], "test_results": grade["test_results"],
        "n_passed": grade["n_passed"], "n_failed": grade["n_failed"],
        "state_diff": grade.get("state_diff"), "irreversible_damage": grade.get("irreversible_damage"),
        "findings": len(result.findings), "plan_steps": len(result.plan),
        "file_edits": sorted({e["content"]["path"] for e in tracer.of_type("file_edit")}),
        "unauthorized_actions": {"count": len(unauthorized), "list": unauthorized},
        "total_tokens": sum(e["tokens_in"] + e["tokens_out"] for e in llm_calls),
        "llm_calls": len(llm_calls), "llm_latency_ms": round(sum(e["latency_ms"] for e in llm_calls), 1),
        "end_to_end_latency_ms": round(wall_ms, 1), "cached_llm_calls": sum(e["content"]["cached"] for e in llm_calls),
        "agents": per_agent, "trace_events": len(tracer.events),
        "trace_valid": not problems, "trace_problems": problems[:10],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--model", help="override the model in the config")
    ap.add_argument("--runs-dir", type=Path, default=RUNS)
    ap.add_argument("--fault", help="TYPE:FACT, e.g. incorrect_result:F2")
    ap.add_argument("--clean-dir", type=Path, default=CLEAN, help="where the matching clean runs are")
    ap.add_argument("--no-reading", action="store_true", help="the no-reading test: code-reading tools disabled")
    args = ap.parse_args(argv)
    cfg = yaml.safe_load(CONFIG.read_text())
    if args.model:
        cfg["llm"]["model"] = args.model
    fault = None
    if args.fault:
        ftype, fact = args.fault.split(":")
        fault = {"type": ftype, "fact": fact}
    try:
        m = run_task(args.task, args.seed, cfg=cfg, runs_dir=args.runs_dir, force=args.force, fault=fault,
                     clean_dir=args.clean_dir, no_reading=args.no_reading)
    except RateLimitExhausted as e:
        print(f"stopping: {e}. Rerun the same command later; finished model calls are cached.")
        return 2
    print(json.dumps({k: m[k] for k in ("run_name", "task_success", "n_passed", "n_failed", "findings",
                                        "plan_steps", "file_edits", "unauthorized_actions", "total_tokens",
                                        "llm_calls", "end_to_end_latency_ms", "trace_valid")}
                     | ({"fault_propagated": m["fault_propagated"]} if fault else {}), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
