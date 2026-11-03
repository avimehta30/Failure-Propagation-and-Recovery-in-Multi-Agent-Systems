"""Researcher: reads the Lifeline workspace and reports separate findings, one per fact."""

from __future__ import annotations

from agents.base import Agent, ToolUse

SYSTEM = """You are the researcher on a small software team. The team works on Lifeline, a codebase you have never seen before, so you must read its code to learn how it works. You cannot change files.

Tools (call exactly one per reply):
- list_dir {"path": "."}
- search_code {"query": "text to find"}
- read_function {"path": "core/ids.py", "name": "function_or_ClassName"}
- read_file {"path": "registry/register.py", "start_line": 1}

Reply with ONE JSON object only. Either a tool call:
{"tool": "search_code", "args": {"query": "household"}}
or, when you know enough, your final answer:
{"final": {"findings": [{"id": "R1", "statement": "...", "file": "path/to/file.py"}]}}

Rules for findings:
- One finding per fact: a rule, format, threshold, function signature or behaviour that matters for the ticket.
- Be specific: exact names, numbers, formats and signatures, as written in the code.
- Only report what you read in the code, and cite the file it came from.
- If a function already exists that does what the ticket needs (or part of it), report its exact name and signature so the team can reuse it.
- Report how the code works. Do not plan or write the change; the planner does that."""


class Researcher(Agent):
    name = "researcher"
    system_prompt = SYSTEM
    min_tool_calls = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._uses: list[ToolUse] = []

    def tool_parents(self, tool, args, llm_id, uses):
        self._uses = uses
        return [llm_id]

    def check_final(self, final):
        if not self._uses and self.min_tool_calls:
            return "you have not read any code yet; explore the workspace first."
        findings = final.get("findings") if isinstance(final, dict) else None
        if not isinstance(findings, list) or not findings:
            return 'it must be {"findings": [...]} with at least one finding.'
        ids = set()
        for f in findings:
            if not isinstance(f, dict) or not all(isinstance(f.get(k), str) and f.get(k) for k in ("id", "statement", "file")):
                return "every finding needs a string id, statement and file."
            if f["id"] in ids:
                return f"finding id {f['id']} is used twice."
            ids.add(f["id"])
        return None


def user_message(ticket: str) -> str:
    return f"Ticket:\n{ticket.strip()}\n\nExplore the code and report your findings. Reply with one JSON object."


def finding_sources(finding: dict, uses: list[ToolUse]) -> list[str]:
    """tool_result events that showed the cited file (read it, or a search hit in it)."""
    cited = finding["file"].strip().lstrip("./")
    ids = []
    for u in uses:
        path = str(u.args.get("path", "")).strip().lstrip("./")
        if (u.tool in ("read_file", "read_function") and path == cited) or (
                u.tool == "search_code" and f"{cited}:" in u.result.output):
            ids.append(u.result.result_id)
    return ids


def redo_message(ticket: str, finding: dict, reason: str) -> str:
    """Always-verify baseline: ask for one rejected finding to be re-checked."""
    return (f"Ticket:\n{ticket.strip()}\n\nYour finding {finding['id']} ({finding.get('file', '')}): "
            f"\"{finding.get('statement', '')}\" was rejected by the verifier: {reason}\n"
            f"Re-check the code and report the corrected finding, with id {finding['id']}. "
            "Reply with one JSON object.")
