"""Check that every run behind the results is internally consistent and graded correctly.

    python -m analysis.verify_runs          # about a minute; exit code 0 if everything checks out

Reads runs/baseline/, runs/faults/ and runs/recovery/ (rebuild them with harness.run_grid, which
replays from the response cache). For every run it:

  regrades    the saved workspace from scratch with the hidden tests or the expected final state,
              and compares every check (and the outbox damage) with what the run recorded;
  traces      each file the agents wrote: its last edit in the trace must be the saved file;
  recomputes  whether each fault spread, from the trace and the matching clean run;
  matches     tokens, model calls and the grade in metrics.json against trace.jsonl, the model
              against the config, and no agent session longer than max_steps;
  links       each fault run to its clean run and each recovery run to its fault run;

and finally checks that results/ is exactly what analysis.summarize makes from these runs
(latency columns excepted: a replay measures the replay, not the original model time).

This shows the results follow from the recorded runs. It cannot show the recorded model replies
are genuine; for that, rerun with your own key and the cache moved aside (see the README).
"""

from __future__ import annotations

import csv
import io
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from analysis import summarize
from harness.grading import run_hidden_tests
from harness.ops import grade_ops
from harness.propagation import analyze
from harness.run_experiment import CONFIG, RUNS
from harness.tasks import load_task

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"


class Report:
    def __init__(self):
        self.problems = Counter()
        self.examples = []

    def flag(self, run: str, what: str) -> None:
        self.problems[what] += 1
        if len(self.examples) < 30:
            self.examples.append(f"{run}: {what}")


def load_runs(folder: Path) -> list[tuple[Path, dict, list[dict]]]:
    runs = []
    for d in sorted(folder.glob("*/")):
        if (d / "metrics.json").exists() and (d / "trace.jsonl").exists():
            events = [json.loads(line) for line in (d / "trace.jsonl").read_text().splitlines()]
            runs.append((d, json.loads((d / "metrics.json").read_text()), events))
    return runs


def sessions(events: list[dict], agent: str) -> list[int]:
    """Steps used in each session of an agent (always-verify starts a new session for each redo)."""
    out, current = [], 0
    for e in events:
        if e["type"] == "llm_call" and e["agent"] == agent:
            step = e["content"].get("step") or 0
            if step == 1 and current:
                out.append(current)
                current = 0
            current = max(current, step)
    return out + ([current] if current else [])


def edits_match_workspace(d: Path, events: list[dict]) -> bool:
    """Each file's last recorded edit in the trace must be what is in the saved workspace."""
    last = {e["content"]["path"]: e["content"].get("after") for e in events if e["type"] == "file_edit"}
    for path, after in last.items():
        f = d / "workspace" / path
        if after is not None and (not f.exists() or f.read_text() != after):
            return False
    return True


def check_run(rep: Report, d: Path, m: dict, events: list[dict], cfg: dict) -> None:
    name = m["run_name"]
    if (d / "workspace").exists() and not edits_match_workspace(d, events):
        rep.flag(name, "workspace files differ from the edits in the trace")
    calls = [e for e in events if e["type"] == "llm_call"]
    if m.get("model") != cfg["llm"]["model"]:
        rep.flag(name, f"model {m.get('model')} is not the configured {cfg['llm']['model']}")
    if m["llm_calls"] != len(calls):
        rep.flag(name, "model-call count differs from the trace")
    if m["total_tokens"] != sum(e["tokens_in"] + e["tokens_out"] for e in calls):
        rep.flag(name, "token count differs from the trace")
    graded = [e for e in events if e["type"] == "test_result"]
    if not graded or graded[-1]["content"]["test_results"] != m["test_results"] \
            or graded[-1]["content"]["passed"] != m["task_success"]:
        rep.flag(name, "grade differs from the trace")
    if m["task_success"] != all(v == "passed" for v in m["test_results"].values()):
        rep.flag(name, "task_success disagrees with its checks")
    if not m["trace_valid"]:
        rep.flag(name, "trace has events without valid parents")
    for agent in ("researcher", "planner", "executor"):
        if any(s > cfg["max_steps"] for s in sessions(events, agent)):
            rep.flag(name, f"{agent} session longer than max_steps")


def regrade(d: Path, m: dict) -> str | None:
    task = load_task(m["task_id"])
    workspace = d / "workspace"
    if not workspace.exists():
        return "workspace missing"
    g = grade_ops(task, workspace, m["seed"]) if task.meta.get("scripts") else run_hidden_tests(task, workspace)
    if g["test_results"] != m["test_results"]:
        return "regrading gives different check results"
    if g.get("irreversible_damage") is not None and g["irreversible_damage"] != m["irreversible_damage"]:
        return "regrading gives different outbox damage"
    return None


def check_results(rep: Report) -> int:
    """results/*.csv must be what summarize makes from runs/ (latency columns excepted)."""
    clean, faults, recovery = (summarize.load(RUNS / f) for f in ("baseline", "faults", "recovery"))
    tables = {
        "clean": summarize.clean_table(clean),
        "fault_types": summarize.fault_type_table(faults),
        "accidental": summarize.fault_table(faults, "accidental"),
        "adversarial": summarize.fault_table(faults, "adversarial"),
        "full_restart": summarize.recovery_table(recovery, "full_restart"),
        "always_verify": summarize.recovery_table(recovery, "always_verify"),
        "recovery_overview": summarize.recovery_overview(faults, recovery),
    }
    for name, rows in tables.items():
        path = RESULTS / f"summary_{name}.csv"
        if not path.exists():
            rep.flag(f"results/{path.name}", "missing")
            continue
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows({k: (";".join(v) if isinstance(v, list) else v) for k, v in r.items()} for r in rows)
        made, saved = list(csv.DictReader(io.StringIO(buf.getvalue()))), list(csv.DictReader(path.open()))
        strip = lambda rows: [{k: v for k, v in r.items() if "latency" not in k} for r in rows]  # noqa: E731
        if strip(made) != strip(saved):
            rep.flag(f"results/{path.name}", "does not match the runs")
    return len(tables)


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text())
    clean, faults, recovery = (load_runs(RUNS / f) for f in ("baseline", "faults", "recovery"))
    if not clean or not faults or not recovery:
        print("No runs found. Rebuild them first (free, from the response cache):\n"
              "    python -m harness.run_grid clean && python -m harness.run_grid faults\n"
              "    python -m harness.run_grid restart && python -m harness.run_grid verify")
        return 1
    rep = Report()
    clean_by = {(m["task_id"], m["seed"]): m for _, m, _ in clean}
    fault_by = {m["run_name"]: m for _, m, _ in faults}

    for d, m, events in clean:
        check_run(rep, d, m, events, cfg)
        if any(e["type"] == "fault_injected" for e in events):
            rep.flag(m["run_name"], "clean run contains an injected fault")
    for d, m, events in faults:
        check_run(rep, d, m, events, cfg)
        c = clean_by.get((m["task_id"], m["seed"]))
        if c is None:
            rep.flag(m["run_name"], "no matching clean run")
            continue
        if bool(m.get("clean_success")) != c["task_success"]:
            rep.flag(m["run_name"], "recorded clean result differs from the clean run")
        if any(e["type"] == "fault_injected" for e in events) != m["propagation"]["injected"]:
            rep.flag(m["run_name"], "injected-fault record differs from the trace")
        if analyze(m["task_id"], m["fault"], events, m, c)["fault_propagated"] != m["fault_propagated"]:
            rep.flag(m["run_name"], "spread verdict differs when recomputed")
    for d, m, events in recovery:
        check_run(rep, d, m, events, cfg)
        r, f = m["recovery"], fault_by.get(m["recovery"]["faulty_run"])
        if f is None:
            rep.flag(m["run_name"], "its fault run is missing")
            continue
        if r["recovered_success"] != m["task_success"] or r["faulty_run_success"] != f["task_success"]:
            rep.flag(m["run_name"], "recorded outcomes differ from the runs")
        if m["fault"] != f["fault"] or m["seed"] != f["seed"]:
            rep.flag(m["run_name"], "different fault or seed from its fault run")

    everything = clean + faults + recovery
    with ThreadPoolExecutor(6) as pool:
        for (d, m, _), problem in zip(everything, pool.map(lambda r: regrade(r[0], r[1]), everything)):
            if problem:
                rep.flag(m["run_name"], problem)
    n_tables = check_results(rep)

    print(f"Checked {len(clean)} clean, {len(faults)} fault and {len(recovery)} recovery runs "
          f"({len(everything)} regraded from their workspaces) and {n_tables} result tables.")
    if not rep.problems:
        print("Everything is consistent.")
        return 0
    print(f"{sum(rep.problems.values())} problems:")
    for what, n in rep.problems.most_common():
        print(f"  {n:4}  {what}")
    print("Examples:")
    for line in rep.examples:
        print("   ", line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
