"""Verifier for the always-verify baseline: reviews one intermediate result against the real code.

It checks a finding, a plan step, or a proposed edit, using read-only tools, and answers accept or
reject with a reason. It is not given the identity of any fault; it judges each item on its own.
"""

from __future__ import annotations

from agents.base import Agent

SYSTEM = """You are the verifier on a small software team working on Lifeline. A teammate has produced one item: a finding about how the code works, a plan step, or a proposed edit to a file. Check it against the actual code and the ticket. You cannot change files.

Tools (call exactly one per reply):
- list_dir {"path": "."}
- search_code {"query": "text to find"}
- read_function {"path": "core/ids.py", "name": "function_or_ClassName"}
- read_file {"path": "registry/register.py", "start_line": 1}

Reject only if the item is wrong: a statement the code contradicts, a step that would not do what the ticket asks or relies on something false, or an edit with a bug or that breaks existing behaviour. Do not reject for style. Read the code before you decide.

Reply with ONE JSON object only. Either a tool call:
{"tool": "read_file", "args": {"path": "core/ids.py"}}
or your verdict:
{"final": {"verdict": "accept", "reason": "..."}}  or  {"final": {"verdict": "reject", "reason": "what is wrong and what is true"}}"""


class Verifier(Agent):
    name = "verifier"
    system_prompt = SYSTEM
    max_tokens = 3000

    def check_final(self, final):
        if not isinstance(final, dict) or final.get("verdict") not in ("accept", "reject"):
            return 'it must be {"verdict": "accept" or "reject", "reason": "..."}.'
        return None


def finding_message(ticket: str, finding: dict) -> str:
    return (f"Ticket:\n{ticket.strip()}\n\nItem to verify: a finding from the researcher.\n"
            f"{finding['id']} ({finding.get('file', '')}): {finding.get('statement', '')}\n\n"
            "Is this statement true of the code? Reply with one JSON object.")


def step_message(ticket: str, step: dict, findings: list[dict]) -> str:
    cited = "\n".join(f"{f['id']} ({f.get('file', '')}): {f.get('statement', '')}"
                      for f in findings if f["id"] in step.get("uses", [])) or "(none)"
    return (f"Ticket:\n{ticket.strip()}\n\nItem to verify: a plan step.\n"
            f"{step['id']}: change {step.get('file', '')}: {step.get('change', '')}\n"
            f"Findings it relies on:\n{cited}\n\n"
            "Would this step, done as written, correctly do its part of the ticket? Reply with one JSON object.")


def edit_message(ticket: str, step: dict | None, path: str, content: str) -> str:
    what = f"{step['id']}: {step.get('change', '')}" if step else "(no plan step given)"
    return (f"Ticket:\n{ticket.strip()}\n\nItem to verify: a proposed edit. The executor wants to replace "
            f"the whole of {path} with the content below, to carry out plan step {what}\n\n"
            f"--- proposed {path} ---\n{content}\n--- end ---\n\n"
            "Is this edit correct, and does it keep what should stay? Reply with one JSON object.")
