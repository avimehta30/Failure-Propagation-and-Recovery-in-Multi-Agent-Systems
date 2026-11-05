"""Decide whether a text or payment is already in an outbox.

Selective recovery should call this before appending a send. The check only
reads records. It never deletes or edits an outbox line.

    python -m harness.outbox_guard                  # scan runs/recovery/*__full_restart
    python -m harness.outbox_guard runs/recovery

A full restart copies the faulty run's outbox into the new workspace and may
append more lines. This report counts how many of those new lines repeat a
send already in the copied prefix. Same household, template, and parameters
count as the same text. Same household, amount, and key count as the same
payment. Those are the keys in harness.outbox_keys, which grading uses too.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from harness.outbox_keys import KEYS

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"

NAMES = {
    "sms": "outbox/sms.jsonl",
    "payment": "outbox/payments.jsonl",
    "payments": "outbox/payments.jsonl",
    **{name: name for name in KEYS},
}


def outbox_name(kind: str) -> str:
    try:
        return NAMES[kind]
    except KeyError:
        raise ValueError(f"unknown outbox {kind!r}; expected one of {sorted(NAMES)}") from None


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"_unparsed": line})
    return out


def already_sent(existing: list[dict], candidate: dict, kind: str) -> bool:
    """True when candidate matches a record already in existing. Does not modify either."""
    key = KEYS[outbox_name(kind)]
    want = key(candidate)
    return any(key(record) == want for record in existing)


def sends_to_skip(existing: list[dict], candidates: list[dict], kind: str) -> list[dict]:
    """Candidates that would repeat a send.

    Walks candidates in order. One that is not already present is treated as
    sent, so a later copy of that same send is skipped too. existing is not modified.
    """
    key = KEYS[outbox_name(kind)]
    seen = {key(record) for record in existing}
    skipped = []
    for candidate in candidates:
        mark = key(candidate)
        if mark in seen:
            skipped.append(candidate)
        else:
            seen.add(mark)
    return skipped


def classify_restart(prefix: list[dict], actual: list[dict], kind: str) -> dict:
    """Compare a copied outbox (prefix) with the file after a restart (actual)."""
    name = outbox_name(kind)
    n = len(prefix)
    intact = actual[:n] == prefix
    added = actual[n:] if intact else []
    skipped = sends_to_skip(prefix, added, name) if intact else []
    key = KEYS[name]
    return {
        "prefix_intact": intact,
        "prefix": n,
        "added": len(added) if intact else None,
        "would_block": len(skipped) if intact else None,
        "blocked_keys": [list(key(record)) for record in skipped],
    }


def _outbox_path(run: Path, name: str) -> Path:
    return run / "workspace" / "data" / name


def guard_one(recovery_run: Path, faults_dir: Path) -> dict | None:
    """One full-restart folder. None when it has no metrics or no named faulty run."""
    metrics_path = recovery_run / "metrics.json"
    if not metrics_path.exists():
        return None
    metrics = json.loads(metrics_path.read_text())
    faulty_name = (metrics.get("recovery") or {}).get("faulty_run")
    if not faulty_name:
        return None
    fault_run = faults_dir / faulty_name
    found = fault_run.is_dir()
    outboxes = {}
    for name in KEYS:
        if not found:
            outboxes[name] = {"prefix_intact": False, "prefix": None, "added": None,
                              "would_block": None, "blocked_keys": []}
            continue
        prefix = read_jsonl(_outbox_path(fault_run, name))
        actual = read_jsonl(_outbox_path(recovery_run, name))
        outboxes[name] = classify_restart(prefix, actual, name)
    return {
        "run_name": recovery_run.name,
        "task_id": metrics.get("task_id"),
        "seed": metrics.get("seed"),
        "faulty_run": faulty_name,
        "fault_run_found": found,
        "outboxes": outboxes,
    }


def guard_report(recovery_dir: Path, faults_dir: Path | None = None) -> list[dict]:
    recovery_dir = Path(recovery_dir)
    faults_dir = Path(faults_dir) if faults_dir is not None else recovery_dir.parent / "faults"
    runs = sorted(p for p in recovery_dir.glob("*__full_restart") if p.is_dir())
    return [row for run in runs if (row := guard_one(run, faults_dir)) is not None]


def _print_report(rows: list[dict]) -> None:
    if not rows:
        print("no full-restart runs found")
        return
    blocked = 0
    added = 0
    for row in rows:
        parts = []
        if not row["fault_run_found"]:
            print(f"{row['run_name']}: faulty workspace missing")
            continue
        for name, info in row["outboxes"].items():
            label = name.split("/")[-1].split(".")[0]
            if info["would_block"] is None:
                parts.append(f"{label}: prefix changed")
            else:
                parts.append(f"{label}: block {info['would_block']}/{info['added']}")
                blocked += info["would_block"]
                added += info["added"]
        print(f"{row['run_name']}: {', '.join(parts)}")
    print(f"total: would block {blocked} of {added} new sends")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    recovery = Path(args[0]) if args else RUNS / "recovery"
    faults = Path(args[1]) if len(args) > 1 else None
    _print_report(guard_report(recovery, faults))
    return 0


if __name__ == "__main__":
    sys.exit(main())
