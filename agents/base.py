"""The tool-use loop every agent runs in.

Each turn the model replies with ONE JSON object: a tool call {"tool": ..., "args": {...}}
or its final answer {"final": {...}}. Tool calls go through env/tools.py; the agent never
touches files itself. Every model call is logged as an llm_call event.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from env.tools import ToolBox, ToolResult
from tracing.trace import Tracer

KEEP_FULL_RESULTS = 2          # older tool results are shortened so the prompt stays small
SHORTENED_CHARS = 600
MAX_RESULT_CHARS = 7000


@dataclass
class ToolUse:
    tool: str
    args: dict
    result: ToolResult


@dataclass
class AgentRun:
    final: dict | None
    final_llm_id: str
    steps: int
    exhausted: bool
    tool_uses: list[ToolUse] = field(default_factory=list)
    llm_ids: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0


class Agent:
    name = "agent"
    system_prompt = ""
    max_tokens = 1500

    def __init__(self, llm, tools: ToolBox, tracer: Tracer, *, max_steps: int = 10, seed: int = 0):
        self.llm, self.tools, self.tracer = llm, tools, tracer
        self.max_steps, self.seed = max_steps, seed

    # Hooks for subclasses -------------------------------------------------
    def check_final(self, final) -> str | None:
        """Return a problem description if the final answer is unusable, else None."""
        return None

    def tool_parents(self, tool: str, args: dict, llm_id: str, uses: list[ToolUse]) -> list[str]:
        """Which events a tool call depends on. By default: the model call that asked for it."""
        return [llm_id]

    # The loop --------------------------------------------------------------
    def run(self, user_message: str, parent_ids: list[str]) -> AgentRun:
        messages = [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user_message}]
        result_slots: list[int] = []
        last_ids = list(parent_ids)
        run = AgentRun(None, "", 0, False)
        for step in range(1, self.max_steps + 1):
            reply = self.llm.chat(_compact(messages, result_slots), seed=self.seed, max_tokens=self.max_tokens)
            llm = self.tracer.log(self.name, "llm_call",
                                  {"step": step, "prompt_tail": messages[-1]["content"][-1500:],
                                   "response": reply.text, "cached": reply.cached},
                                  last_ids, tokens_in=reply.tokens_in, tokens_out=reply.tokens_out,
                                  latency_ms=reply.latency_ms)
            run.steps, run.final_llm_id = step, llm["id"]
            run.llm_ids.append(llm["id"])
            run.tokens_in += reply.tokens_in
            run.tokens_out += reply.tokens_out
            run.latency_ms += reply.latency_ms
            messages.append({"role": "assistant", "content": reply.text})
            action = parse_action(reply.text)

            if action is None:
                note = 'That was not one JSON object. Reply with exactly one JSON object: {"tool": ..., "args": {...}} or {"final": {...}}.'
            elif "final" in action:
                problem = self.check_final(action["final"])
                if problem is None:
                    run.final = action["final"]
                    return run
                note = f"Your final answer cannot be used: {problem} Fix it and reply with one JSON object."
            elif isinstance(action.get("tool"), str):
                args = action.get("args") if isinstance(action.get("args"), dict) else {}
                parents = self.tool_parents(action["tool"], args, llm["id"], run.tool_uses)
                result = self.tools.dispatch(self.name, action["tool"], args, parents)
                run.tool_uses.append(ToolUse(action["tool"], args, result))
                output = result.output if len(result.output) <= MAX_RESULT_CHARS else (
                    result.output[:MAX_RESULT_CHARS] + "\n[output cut]")
                messages.append({"role": "user", "content": f"Result of {action['tool']}:\n{output}\n\n"
                                 + _next_prompt(self.max_steps - step)})
                result_slots.append(len(messages) - 1)
                last_ids = [llm["id"], result.result_id]
                continue
            else:
                note = 'Reply with {"tool": "<name>", "args": {...}} or {"final": {...}}.'
            messages.append({"role": "user", "content": note + " " + _next_prompt(self.max_steps - step)})
            last_ids = [llm["id"]]
        run.exhausted = True
        return run


def _next_prompt(steps_left: int) -> str:
    if steps_left <= 1:
        return "This is your LAST step: reply with your final answer now, not a tool call."
    return (f"You have {steps_left} steps left. Next: ONE JSON object, either another tool call "
            "or your final answer as soon as you know enough.")


def parse_action(text: str) -> dict | None:
    """The first JSON object in the reply, tolerating code fences and text around it."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = text.find("{", start + 1)
    return None


def _compact(messages: list[dict], result_slots: list[int]) -> list[dict]:
    """Shorten all but the last few tool results, so long explorations stay within the model's budget."""
    old = set(result_slots[:-KEEP_FULL_RESULTS]) if len(result_slots) > KEEP_FULL_RESULTS else set()
    out = []
    for i, m in enumerate(messages):
        if i in old and len(m["content"]) > SHORTENED_CHARS:
            m = {"role": m["role"], "content": m["content"][:SHORTENED_CHARS] + "\n[earlier result shortened]"}
        out.append(m)
    return out
