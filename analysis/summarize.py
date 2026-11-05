"""Aggregate runs/ into summary tables.

    python -m analysis.summarize            # writes results/summary.md and results/summary_*.csv

Reads runs/baseline/ (clean), runs/faults/ (fault runs) and runs/recovery/ (full restart).
Accidental and adversarial faults are always reported in separate tables.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
OUT = ROOT / "results"   # tracked in git, unlike runs/


def load(folder: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(folder.glob("*/metrics.json"))] if folder.exists() else []


def _mean(xs):
    return round(statistics.mean(xs), 1) if xs else None


def _sd(xs):
    return round(statistics.stdev(xs), 1) if len(xs) > 1 else 0.0


def _damage(m: dict) -> int:
    """All outbox damage: sends that are missing, sent wrongly, or not audited. Duplicate and
    malformed records are already counted in "wrong" (harness/ops.py), so they are not added."""
    total = 0
    for d in (m.get("irreversible_damage") or {}).values():
        total += sum(d.get(k, 0) for k in ("missing", "wrong", "unaudited_payments"))
    return total


def _bad_sends(m: dict) -> int:
    """Texts and payments sent that should not have been (wrong, extra copies, malformed)."""
    return sum(d.get("wrong", 0) for d in (m.get("irreversible_damage") or {}).values())


def clean_table(clean: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for m in clean:
        by[m["task_id"]].append(m)
    rows = []
    for task, ms in sorted(by.items()):
        rows.append({
            "task": task, "tier": ms[0]["tier"], "runs": len(ms),
            "success": f"{sum(m['task_success'] for m in ms)}/{len(ms)}",
            "checks_passed": f"{sum(m['n_passed'] for m in ms)}/{sum(m['n_passed'] + m['n_failed'] for m in ms)}",
            "tokens_mean": _mean([m["total_tokens"] for m in ms]), "tokens_sd": _sd([m["total_tokens"] for m in ms]),
            "latency_s_mean": _mean([m["end_to_end_latency_ms"] / 1000 for m in ms]),
            "llm_calls_mean": _mean([m["llm_calls"] for m in ms]),
            "unauthorized": sum(m["unauthorized_actions"]["count"] for m in ms),
            "irreversible_damage": sum(_damage(m) for m in ms),
            "trace_valid": f"{sum(m['trace_valid'] for m in ms)}/{len(ms)}",
        })
    return rows


def fault_table(faults: list[dict], category: str) -> list[dict]:
    by = defaultdict(list)
    for m in faults:
        if m["fault"]["category"] == category:
            by[(m["fault"]["type"], m["task_id"], m["fault"]["fact"])].append(m)
    rows = []
    for (ftype, task, fact), ms in sorted(by.items()):
        props = [m["propagation"] for m in ms]
        injected = [p for p in props if p["injected"]]
        rows.append({
            "fault": ftype, "task": task, "fact": fact, "runs": len(ms),
            "injected": f"{len(injected)}/{len(ms)}",
            "propagated": f"{sum(m['fault_propagated'] for m in ms)}/{len(ms)}",
            "reached_in_trace": f"{sum(p.get('trace_reached_products', False) for p in props)}/{len(ms)}",
            "outcome_changed": f"{sum(p.get('outcome_changed', False) for p in props)}/{len(ms)}",
            "success": f"{sum(m['task_success'] for m in ms)}/{len(ms)}",
            "clean_success": f"{sum(bool(m.get('clean_success')) for m in ms)}/{len(ms)}",
            "affected_files_cited": sorted({f for p in injected for f in p.get("affected_files", [])}),
            "affected_files_context": sorted({f for p in injected for f in p.get("context_reached", {}).get("file_edits", [])}),
            "affected_stages": sorted({s for p in injected for s in p.get("affected_stages", [])}),
            "wasted_tokens_mean": _mean([p["wasted_work"]["tokens"] for p in injected]),
            "unauthorized": sum(m["unauthorized_actions"]["count"] for m in ms),
            "bad_sends": sum(_bad_sends(m) for m in ms),
            "irreversible_damage": sum(_damage(m) for m in ms),
            "attack_followed": (f"{sum(bool(p.get('attack') and p['attack']['followed']) for p in injected)}/{len(ms)}"
                                if ftype == "malicious_instruction" else ""),
        })
    return rows


def fault_type_table(faults: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for m in faults:
        by[(m["fault"]["category"], m["fault"]["type"])].append(m)
    rows = []
    for (cat, ftype), ms in sorted(by.items()):
        rows.append({"category": cat, "fault": ftype, "runs": len(ms),
                     "injected": sum(m["propagation"]["injected"] for m in ms),
                     "propagated": sum(m["fault_propagated"] for m in ms),
                     "propagation_rate": f"{100 * sum(m['fault_propagated'] for m in ms) / len(ms):.0f}%",
                     "task_success": f"{sum(m['task_success'] for m in ms)}/{len(ms)}",
                     "unauthorized": sum(m["unauthorized_actions"]["count"] for m in ms),
                     "bad_sends": sum(_bad_sends(m) for m in ms),
                     "irreversible_damage": sum(_damage(m) for m in ms)})
    return rows


def recovery_table(recovery: list[dict], method: str = "full_restart") -> list[dict]:
    by = defaultdict(list)
    for m in recovery:
        if m.get("recovery") and m["recovery"]["method"] == method:
            by[(m["fault"]["category"], m["fault"]["type"], m["task_id"], m["fault"]["fact"])].append(m)
    rows = []
    for (cat, ftype, task, fact), ms in sorted(by.items()):
        rs = [m["recovery"] for m in ms]
        rows.append({"category": cat, "fault": ftype, "task": task, "fact": fact, "runs": len(ms),
                     "faulty_success": f"{sum(r['faulty_run_success'] for r in rs)}/{len(ms)}",
                     "recovered_success": f"{sum(r['recovered_success'] for r in rs)}/{len(ms)}",
                     "recomputed_stages": 3, "retained_items": 0,
                     "recovery_tokens_mean": _mean([r["recovery_tokens"] for r in rs]),
                     "recovery_latency_s_mean": _mean([r["recovery_latency_ms"] / 1000 for r in rs]),
                     "bad_sends": sum(_bad_sends(m) for m in ms),
                     "damage_left_after_recovery": sum(_damage(m) for m in ms)})
        if method == "always_verify":
            row = rows[-1]
            for k in ("recomputed_stages", "retained_items"):
                row.pop(k)
            row.update({"caught_fault": f"{sum(r['caught_fault'] for r in rs)}/{len(ms)}",
                        "rejected_mean": _mean([r["items_rejected"] for r in rs]),
                        "false_rejections": sum(r["false_rejections"] for r in rs),
                        "checked_mean": _mean([r["items_checked"] for r in rs]),
                        "verifier_tokens_mean": _mean([r["verifier_tokens"] for r in rs]),
                        "verifier_latency_s_mean": _mean([r["verifier_latency_ms"] / 1000 for r in rs])})
    return rows


def recovery_overview(faults: list[dict], recovery: list[dict]) -> list[dict]:
    """One row per policy and fault category, over the same fault cases (report Table 1)."""
    rows = []
    clean_ok = {m["run_name"]: bool(m.get("clean_success")) for m in faults}
    for cat in ("accidental", "adversarial"):
        base = [m for m in faults if m["fault"]["category"] == cat]
        rows.append({"category": cat, "policy": "no_recovery", "cases": len(base),
                     "passed": f"{sum(m['task_success'] for m in base)}/{len(base)}",
                     "passable_cleanly": sum(bool(m.get("clean_success")) for m in base),
                     "bad_sends": sum(_bad_sends(m) for m in base),
                     "tokens_mean": _mean([m["total_tokens"] for m in base])})
        for method in ("full_restart", "always_verify"):
            ms = [m for m in recovery if m["recovery"]["method"] == method and m["fault"]["category"] == cat]
            rows.append({"category": cat, "policy": method, "cases": len(ms),
                         "passed": f"{sum(m['recovery']['recovered_success'] for m in ms)}/{len(ms)}",
                         "passable_cleanly": sum(clean_ok.get(m["run_name"].rsplit("__", 1)[0], False) for m in ms),
                         "bad_sends": sum(_bad_sends(m) for m in ms),
                         # restart: tokens on top of the faulty run; always-verify: the whole rerun
                         "tokens_mean": _mean([m["recovery"]["recovery_tokens"] for m in ms])})
    return rows


def _md(rows: list[dict], title: str) -> str:
    if not rows:
        return f"### {title}\n\n(no runs yet)\n"
    cols = list(rows[0])
    fmt = lambda v: ", ".join(v) if isinstance(v, list) else ("" if v is None else str(v))  # noqa: E731
    lines = [f"### {title}", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def _csv(rows: list[dict], path: Path) -> None:
    if rows:
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows({k: (";".join(v) if isinstance(v, list) else v) for k, v in r.items()} for r in rows)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    clean, faults, recovery = load(RUNS / "baseline"), load(RUNS / "faults"), load(RUNS / "recovery")
    tables = {
        "clean": ("Clean baseline (no faults)", clean_table(clean)),
        "fault_types": ("Propagation by fault type", fault_type_table(faults)),
        "accidental": ("Accidental faults", fault_table(faults, "accidental")),
        "adversarial": ("Adversarial faults", fault_table(faults, "adversarial")),
        "full_restart": ("Full restart (recovery baseline)", recovery_table(recovery, "full_restart")),
        "always_verify": ("Always-verify (verification baseline, same faults)", recovery_table(recovery, "always_verify")),
        "recovery_overview": ("Recovery overview (bad_sends: texts and payments sent that should not have been)",
                              recovery_overview(faults, recovery)),
    }
    out = ["# Phase 1 results", "",
           f"{len(clean)} clean runs, {len(faults)} fault runs, {len(recovery)} recovery runs.", ""]
    for name, (title, rows) in tables.items():
        out.append(_md(rows, title))
        _csv(rows, OUT / f"summary_{name}.csv")
    (OUT / "summary.md").write_text("\n".join(out))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
