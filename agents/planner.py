"""Planner: turns the ticket and the researcher's findings into one plan step per file. No tools."""

from __future__ import annotations

from agents.base import Agent

SYSTEM = """You are the planner on a small software team working on Lifeline. You have no tools: you work only from the ticket and the researcher's findings.

Write an implementation plan with exactly ONE step per file to change or create. Each step says precisely what to change in that file, and cites:
- "uses": the finding ids it relies on, e.g. ["R1", "R2"]
- "after": earlier step ids it depends on, e.g. ["P1"] (empty if none)

Rely only on the findings. Do not invent facts the findings do not state. Prefer reusing existing functions named in the findings over re-implementing their logic. Ops tickets that need a script: one step to write scripts/<name>.py and one step to run it.

Reply with ONE JSON object only:
{"final": {"steps": [{"id": "P1", "file": "path/to/file.py", "change": "what to do, precisely", "uses": ["R1"], "after": []}]}}"""


class Planner(Agent):
    name = "planner"
    system_prompt = SYSTEM

    def __init__(self, *args, finding_ids=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.finding_ids = set(finding_ids)

    def check_final(self, final):
        steps = final.get("steps") if isinstance(final, dict) else None
        if not isinstance(steps, list) or not steps:
            return 'it must be {"steps": [...]} with at least one step.'
        seen = set()
        for s in steps:
            if not isinstance(s, dict) or not all(isinstance(s.get(k), str) and s.get(k) for k in ("id", "file", "change")):
                return "every step needs a string id, file and change."
            if s["id"] in seen:
                return f"step id {s['id']} is used twice."
            for key, valid in (("uses", self.finding_ids), ("after", seen)):
                refs = s.get(key, [])
                if not isinstance(refs, list) or any(r not in valid for r in refs):
                    return f"step {s['id']} cites {key} {refs}, but only {sorted(valid) or 'none'} exist."
            seen.add(s["id"])
        return None


def user_message(ticket: str, findings: list[dict]) -> str:
    lines = "\n".join(f"{f['id']} ({f['file']}): {f['statement']}" for f in findings) or "(no findings)"
    return f"Ticket:\n{ticket.strip()}\n\nResearcher findings:\n{lines}\n\nWrite the plan. Reply with one JSON object."
