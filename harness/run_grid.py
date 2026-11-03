"""Run a batch of experiments from harness/configs/phase1.yaml in parallel, skipping finished runs.

    python -m harness.run_grid clean            # every task x seed, no faults  -> runs/baseline/
    python -m harness.run_grid faults           # the fault grid                -> runs/faults/
    python -m harness.run_grid faults --only T04 --workers 4
    python -m harness.run_grid restart          # full restart of every fault run that was injected -> runs/recovery/
    python -m harness.run_grid verify           # always-verify under the same faults               -> runs/recovery/

Each run is its own process (python -m harness.run_experiment ...), so one failure does not stop
the batch. A one-line summary per run is printed as it finishes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from harness.run_experiment import CLEAN, CONFIG, RUNS, run_name_for
from harness.tasks import all_task_ids


def jobs(kind: str, cfg: dict, only: set[str] | None) -> list[tuple[str, int, dict | None]]:
    seeds = cfg.get("seeds", [0, 1, 2])
    if kind == "clean":
        out = [(t, s, None) for t in all_task_ids() for s in seeds]
    else:
        out = [(f["task"], s, {"type": f["type"], "fact": f["fact"]}) for f in cfg["faults"] for s in seeds]
    return [j for j in out if not only or j[0] in only]


def run_one(task: str, seed: int, fault: dict | None, runs_dir: Path) -> dict:
    cmd = [sys.executable, "-m", "harness.run_experiment", "--task", task, "--seed", str(seed),
           "--runs-dir", str(runs_dir)]
    if fault:
        cmd += ["--fault", f"{fault['type']}:{fault['fact']}"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    path = runs_dir / run_name_for(task, seed, fault) / "metrics.json"
    if not path.exists():
        return {"run_name": run_name_for(task, seed, fault), "error": (proc.stdout + proc.stderr)[-500:]}
    return json.loads(path.read_text())


def run_recovery(method: str, fault_run: Path) -> dict:
    proc = subprocess.run([sys.executable, "-m", "harness.recovery", method, str(fault_run)],
                          capture_output=True, text=True)
    path = RUNS / "recovery" / f"{fault_run.name}__{method}" / "metrics.json"
    if not path.exists():
        return {"run_name": f"{fault_run.name}__{method}", "error": (proc.stdout + proc.stderr)[-500:]}
    return json.loads(path.read_text())


def line(m: dict) -> str:
    if "error" in m:
        return f"{m['run_name']:<34} ERROR {m['error'][-200:]}"
    out = f"{m['run_name']:<34} success={m['task_success']!s:<5} checks={m['n_passed']}/{m['n_passed'] + m['n_failed']}"
    if m.get("recovery"):
        r = m["recovery"]
        out += f" recovered={r['recovered_success']!s:<5} recovery_tokens={r['recovery_tokens']}"
        if r["method"] == "always_verify":
            out += f" caught={r['caught_fault']!s:<5} rejected={r['items_rejected']}/{r['items_checked']} verifier_tokens={r['verifier_tokens']}"
    elif m.get("propagation"):
        p = m["propagation"]
        out += (f" propagated={m['fault_propagated']!s:<5} injected={p['injected']!s:<5}"
                f" cited_files={p.get('affected_files', [])} unauth={m['unauthorized_actions']['count']}")
    return out + f" tokens={m['total_tokens']}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["clean", "faults", "restart", "verify"])
    ap.add_argument("--only", nargs="*", help="task ids to include")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    cfg = yaml.safe_load(CONFIG.read_text())
    if args.kind in ("restart", "verify"):
        method = "full_restart" if args.kind == "restart" else "always_verify"
        injected = [p.parent for p in sorted((RUNS / "faults").glob("*/metrics.json"))
                    if json.loads(p.read_text()).get("propagation", {}).get("injected")
                    and (not args.only or p.parent.name.split("__")[0] in args.only)]
        print(f"{len(injected)} {method} runs -> {RUNS / 'recovery'}", flush=True)
        with ThreadPoolExecutor(args.workers) as pool:
            for fut in as_completed([pool.submit(run_recovery, method, r) for r in injected]):
                print(line(fut.result()), flush=True)
        return 0
    runs_dir = CLEAN if args.kind == "clean" else RUNS / "faults"
    todo = jobs(args.kind, cfg, set(args.only) if args.only else None)
    print(f"{len(todo)} runs -> {runs_dir}", flush=True)
    with ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(run_one, t, s, f, runs_dir) for t, s, f in todo]
        for fut in as_completed(futures):
            print(line(fut.result()), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
