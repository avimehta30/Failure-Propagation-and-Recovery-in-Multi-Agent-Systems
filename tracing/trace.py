"""The run trace: every event is one JSON line in trace.jsonl, linked to the events it came from.

Each event has: id, parent_ids, run_id, timestamp, agent, type, content,
tokens_in, tokens_out, latency_ms.

`parent_ids` is the dependency graph. Plan step P2 has findings R1 and R2 as parents,
the edit to rations.py has P2 as a parent, and so on, giving chains like R2 -> P2 -> E2.
Only task inputs (the ticket) have no parents.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = (
    "llm_call", "message", "tool_call", "tool_result", "finding", "plan_step", "file_edit",
    "script_run", "outbox_write", "state_change", "fault_injected", "unauthorized_action", "test_result",
)


class Tracer:
    def __init__(self, run_id: str, path: Path | None = None):
        self.run_id = run_id
        self.path = Path(path) if path else None
        self.events: list[dict] = []
        self._by_id: dict[str, dict] = {}
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("")

    def log(self, agent: str, type: str, content, parent_ids=(), *, tokens_in: int = 0,
            tokens_out: int = 0, latency_ms: float = 0.0) -> dict:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type!r}")
        parents = list(dict.fromkeys(p for p in parent_ids if p))
        missing = [p for p in parents if p not in self._by_id]
        if missing:
            raise ValueError(f"unknown parent ids {missing}")
        event = {"id": f"e{len(self.events) + 1:04d}", "parent_ids": parents, "run_id": self.run_id,
                 "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                 "agent": agent, "type": type, "content": content,
                 "tokens_in": tokens_in, "tokens_out": tokens_out, "latency_ms": round(latency_ms, 1)}
        self.events.append(event)
        self._by_id[event["id"]] = event
        if self.path:
            with open(self.path, "a") as f:
                f.write(json.dumps(event, default=str) + "\n")
        return event

    def get(self, event_id: str) -> dict:
        return self._by_id[event_id]

    def of_type(self, type: str, agent: str | None = None) -> list[dict]:
        return [e for e in self.events if e["type"] == type and agent in (None, e["agent"])]

    def ancestors(self, event_id: str) -> set[str]:
        return _walk(event_id, lambda i: self._by_id[i]["parent_ids"])

    def descendants(self, event_id: str) -> set[str]:
        children: dict[str, list[str]] = {}
        for e in self.events:
            for p in e["parent_ids"]:
                children.setdefault(p, []).append(e["id"])
        return _walk(event_id, lambda i: children.get(i, []))


def _walk(start: str, step) -> set[str]:
    seen, todo = set(), list(step(start))
    while todo:
        i = todo.pop()
        if i not in seen:
            seen.add(i)
            todo.extend(step(i))
    return seen


def is_task_input(event: dict) -> bool:
    return event["type"] == "message" and isinstance(event["content"], dict) and event["content"].get("task_input")


def load_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def validate_trace(events: list[dict]) -> list[str]:
    """Problems with a trace: bad ids, unknown or later parents, parentless non-input events."""
    problems, seen = [], set()
    for e in events:
        if e["id"] in seen:
            problems.append(f"{e['id']}: duplicate id")
        if e["type"] not in EVENT_TYPES:
            problems.append(f"{e['id']}: unknown type {e['type']!r}")
        for p in e["parent_ids"]:
            if p not in seen:
                problems.append(f"{e['id']}: parent {p} is unknown or comes later")
        if not e["parent_ids"] and not is_task_input(e):
            problems.append(f"{e['id']}: {e['type']} has no parents (only task inputs may)")
        seen.add(e["id"])
    return problems
