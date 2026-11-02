"""The proctor: runs a task through the agents, grades it, and files the result.

    python -m harness.run_experiment --task T01 --seed 0          # one clean run
    python -m harness.run_experiment --task T01 --seed 0 --force  # redo it (LLM replies still cached)

Each run writes runs/<run_name>/{workspace/, trace.jsonl, metrics.json}.
Fault injection and the recovery baselines plug in here in later build steps.
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
from harness.grading import run_hidden_tests
from harness.tasks import ROOT, load_task, make_workspace
from tracing.trace import Tracer, validate_trace

RUNS = ROOT / "runs"
CONFIG = ROOT / "harness" / "configs" / "phase1.yaml"


def run_task(task_id: str, seed: int = 0, *, cfg: dict | None = None, llm=None, run_name: str | None = None,
             runs_dir: Path = RUNS, force: bool = False) -> dict:
    cfg = cfg or yaml.safe_load(CONFIG.read_text())
    task = load_task(task_id)
    run_name = run_name or f"{task_id}__clean__s{seed}"
    run_dir = Path(runs_dir) / run_name
    if (run_dir / "metrics.json").exists() and not force:
        return json.loads((run_dir / "metrics.json").read_text())
    if run_dir.exists():
        shutil.rmtree(run_dir)
    llm = llm or LLM(**cfg["llm"])
    ops = task.meta["kind"] == "ops"
    workspace = make_workspace(task, run_dir / "workspace", seed=seed)
    tracer = Tracer(run_name, run_dir / "trace.jsonl")
    tools = ToolBox(workspace, tracer, allow_run_script=ops, allow_visible_tests=cfg.get("run_visible_tests", False))

    start = time.perf_counter()
    result = Orchestrator(task_id, task.prompt, llm, tools, tracer, max_steps=cfg.get("max_steps", 10),
                          seed=seed, ops=ops).run()
    grade = run_hidden_tests(task, workspace)
    edits = [e["id"] for e in tracer.of_type("file_edit", "executor")]
    tracer.log("harness", "test_result", {k: grade[k] for k in ("passed", "test_results", "n_passed", "n_failed")},
               edits or [result.runs["executor"].final_llm_id or result.task_input_id])
    wall_ms = (time.perf_counter() - start) * 1000

    m = metrics(task, seed, run_name, cfg, tracer, result, grade, wall_ms, getattr(llm, "model", None))
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
    args = ap.parse_args(argv)
    try:
        m = run_task(args.task, args.seed, force=args.force)
    except RateLimitExhausted as e:
        print(f"stopping: {e}. Rerun the same command later; finished model calls are cached.")
        return 2
    print(json.dumps({k: m[k] for k in ("run_name", "task_success", "n_passed", "n_failed", "findings",
                                        "plan_steps", "file_edits", "unauthorized_actions", "total_tokens",
                                        "llm_calls", "end_to_end_latency_ms", "trace_valid")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
