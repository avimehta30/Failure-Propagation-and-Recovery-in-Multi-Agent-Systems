"""Phase 1 recovery baselines. Both are given the identity of the faulty result
(the fault_injected event IDs in the faulty run's trace): we measure recovery, not
detection.

    python -m harness.recovery full_restart runs/faults/T04__incorrect_result-F2__s0

full_restart: reset the workspace code and registry.json / ledger.json / sms_status.json to the
task's starting state, remove the fault, and rerun the whole workflow under the same settings.
Outbox and audit lines written by the faulty run are NOT removed (they were sent); they are
carried into the new workspace and counted as irreversible damage.

always_verify: rerun the task under the identical fault (same task, seed and fault) with a verifier
call reviewing every finding, plan step and edit before it is passed on; a rejected item is redone.
Verifier tokens and latency are recorded separately, with whether it rejected anything derived
from the fault ("caught_fault").

    python -m harness.recovery always_verify runs/faults/T04__incorrect_result-F2__s0

Results go to runs/recovery/<faulty run>__full_restart/ and .../<faulty run>__always_verify/.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

from harness.propagation import descendants
from harness.run_experiment import CONFIG, RUNS, run_task
from tracing.trace import load_trace

APPEND_ONLY = ("outbox/sms.jsonl", "outbox/payments.jsonl", "audit.jsonl")
STAGES = ["researcher", "planner", "executor"]


def full_restart(fault_run: Path, *, cfg: dict | None = None, llm=None, runs_dir: Path = RUNS / "recovery",
                 force: bool = False) -> dict:
    fault_run = Path(fault_run)
    faulty = json.loads((fault_run / "metrics.json").read_text())
    events = load_trace(fault_run / "trace.jsonl")
    fault_ids = [e["id"] for e in events if e["type"] == "fault_injected"]

    def carry_over_sent(workspace: Path) -> None:
        for name in APPEND_ONLY:
            src = fault_run / "workspace" / "data" / name
            if src.exists():
                (workspace / "data" / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, workspace / "data" / name)

    m = run_task(faulty["task_id"], faulty["seed"], cfg=cfg, llm=llm, runs_dir=runs_dir, force=force,
                 run_name=f"{faulty['run_name']}__full_restart", prepare=carry_over_sent, method="full_restart")
    if "recovery" not in m:
        m["fault"] = faulty["fault"]
        m["recovery"] = {
            "method": "full_restart",
            "given_faulty_event_ids": fault_ids,
            "faulty_run": faulty["run_name"],
            "faulty_run_success": faulty["task_success"],
            "fault_propagated": faulty.get("fault_propagated"),
            "recovered_success": m["task_success"],
            "recomputed_stages": STAGES,
            "retained_items": 0,
            "recovery_tokens": m["total_tokens"],
            "recovery_llm_calls": m["llm_calls"],
            "recovery_latency_ms": m["end_to_end_latency_ms"],
            "total_tokens_with_faulty_run": faulty["total_tokens"] + m["total_tokens"],
            "irreversible_damage_from_faulty_run": faulty.get("irreversible_damage"),
        }
        (Path(runs_dir) / m["run_name"] / "metrics.json").write_text(json.dumps(m, indent=2))
    return m


def judge_rejections(events: list[dict]) -> dict:
    """Which verifier rejections hit an item derived from the fault (cited view), and which were false
    alarms. The rejected item is the first non-verifier event above the verdict in the trace."""
    by_id = {e["id"]: e for e in events}
    fault_ids = {e["id"] for e in events if e["type"] == "fault_injected"}
    tainted = fault_ids | descendants(events, fault_ids, through_llm_calls=False)

    def item_of(verdict: dict) -> set[str]:
        out, todo, seen = set(), list(verdict["parent_ids"]), set()
        while todo:
            e = by_id[todo.pop()]
            if e["id"] in seen:
                continue
            seen.add(e["id"])
            if e["agent"] == "verifier":
                todo.extend(e["parent_ids"])
            else:
                out.add(e["id"])
        return out

    rejected = [e for e in events if e["agent"] == "verifier" and e["type"] == "message"
                and e["content"].get("verdict") == "reject"]
    hits = [e for e in rejected if item_of(e) & tainted]
    return {"rejected": len(rejected), "caught": len(hits), "false_alarms": len(rejected) - len(hits),
            "caught_items": [(e["content"]["kind"], e["content"]["item"]) for e in hits],
            "false_alarm_items": [(e["content"]["kind"], e["content"]["item"]) for e in rejected if e not in hits]}


def always_verify(fault_run: Path, *, cfg: dict | None = None, llm=None, runs_dir: Path = RUNS / "recovery",
                  force: bool = False) -> dict:
    fault_run = Path(fault_run)
    faulty = json.loads((fault_run / "metrics.json").read_text())
    fault = {"type": faulty["fault"]["type"], "fact": faulty["fault"]["fact"]}
    name = f"{faulty['run_name']}__always_verify"
    m = run_task(faulty["task_id"], faulty["seed"], cfg=cfg, llm=llm, runs_dir=runs_dir, force=force,
                 run_name=name, fault=fault, method="always_verify", verify=True)
    if "recovery" not in m:
        judged = judge_rejections(load_trace(Path(runs_dir) / name / "trace.jsonl"))
        v = m.get("verification") or {}
        m["recovery"] = {
            "method": "always_verify",
            "faulty_run": faulty["run_name"],
            "faulty_run_success": faulty["task_success"],
            "fault_propagated": m.get("fault_propagated"),
            "recovered_success": m["task_success"],
            "caught_fault": judged["caught"] > 0,
            "items_checked": v.get("checked", 0), "items_rejected": judged["rejected"],
            "false_rejections": judged["false_alarms"],
            "caught_items": judged["caught_items"], "false_alarm_items": judged["false_alarm_items"],
            "items_redone": v.get("redone", 0),
            "verifier_tokens": v.get("verifier_tokens", 0), "verifier_llm_calls": v.get("llm_calls", 0),
            "verifier_latency_ms": round(v.get("latency_ms", 0.0), 1),
            "redo_tokens": v.get("redo_tokens", 0),
            "recovery_tokens": m["total_tokens"],
            "recovery_latency_ms": m["end_to_end_latency_ms"],
        }
        (Path(runs_dir) / name / "metrics.json").write_text(json.dumps(m, indent=2))
    return m


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) >= 2 and args[0] in ("full_restart", "always_verify"):
        cfg = yaml.safe_load(CONFIG.read_text())
        method = full_restart if args[0] == "full_restart" else always_verify
        for run in args[1:]:
            m = method(Path(run), cfg=cfg)
            r = m["recovery"]
            print(f"{m['run_name']}: recovered={r['recovered_success']} tokens={r['recovery_tokens']} "
                  f"latency={r['recovery_latency_ms'] / 1000:.0f}s")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
