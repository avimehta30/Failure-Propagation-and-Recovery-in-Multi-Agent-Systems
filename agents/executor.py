"""Executor: carries out the plan, one logged edit per file, each tied to its plan step."""

from __future__ import annotations

from agents.base import Agent

SYSTEM = """You are the executor on a small software team working on Lifeline. You carry out the planner's plan by editing files.

Tools (call exactly one per reply):
- read_file {"path": "registry/register.py", "start_line": 1}
- list_dir {"path": "."}
- write_file {"path": "registry/register.py", "content": "<the WHOLE new file>", "step": "P1"}
{run_script_line}
Test files are read-only: never add, edit or delete anything under tests/ or any test_*.py file. The team's work is checked by its own tests, which must stay unchanged.
write_file replaces the whole file. Read a file before rewriting it, and keep everything that should stay. Make one write per file, and label it with the plan step it carries out.

Reply with ONE JSON object only. Either a tool call:
{"tool": "read_file", "args": {"path": "registry/register.py"}}
or, when every step is done:
{"final": {"summary": "what you changed", "done_steps": ["P1"]}}"""

RUN_SCRIPT = '- run_script {"path": "scripts/name.py", "step": "P2"}: runs a script you wrote in scripts/ and shows its output\n'


class Executor(Agent):
    name = "executor"
    max_tokens = 4000

    def __init__(self, *args, step_events=None, step_files=None, can_run_scripts=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.step_events = dict(step_events or {})      # plan step id -> plan_step event id
        self.step_files = dict(step_files or {})        # file -> plan step ids for that file, in plan order
        self.system_prompt = SYSTEM.replace("{run_script_line}\n", RUN_SCRIPT if can_run_scripts else "")

    def tool_parents(self, tool, args, llm_id, uses):
        """An edit or script run depends on its plan step and on what was read of that same file."""
        path = str(args.get("path", "")).strip().lstrip("./")
        step = str(args.get("step", ""))
        if step not in self.step_events and self.step_files.get(path):
            # Unlabelled: each plan step names one file, so use the step for this file
            # (the first for a write, the last for a run, as plans write a script then run it).
            candidates = self.step_files[path]
            step = candidates[0] if tool == "write_file" else candidates[-1]
        step_event = self.step_events.get(step)
        if tool not in ("write_file", "run_script") or step_event is None:
            return [llm_id]
        reads = [u.result.result_id for u in uses
                 if u.tool == "read_file" and str(u.args.get("path", "")).strip().lstrip("./") == path]
        return [step_event] + reads

    def check_final(self, final):
        if not isinstance(final, dict):
            return 'it must be {"summary": ..., "done_steps": [...]}.'
        return None


def user_message(ticket: str, steps: list[dict]) -> str:
    def line(s):
        deps = ", ".join(s.get("uses", []) + s.get("after", []))
        return f"{s['id']} [{s['file']}]: {s['change']}" + (f" (based on {deps})" if deps else "")
    plan = "\n".join(line(s) for s in steps) or "(empty plan)"
    return f"Ticket:\n{ticket.strip()}\n\nPlan:\n{plan}\n\nCarry out the plan. Reply with one JSON object."
