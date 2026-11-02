"""Runs researcher -> planner -> executor and records every hand-off in the trace.

Agents talk only through messages sent here. Findings and plan steps are logged as separate
events, so the dependency graph branches: a plan step's parents are the findings it cites
(as the planner received them) and the earlier steps it depends on.

send() is the single place a message is delivered. If the harness attached a fault hook with
intercept_message(sender, receiver, items) -> (items, fault | None), the receiver sees the
altered items, and the items it saw are linked to the fault_injected event. No fault logic here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents import executor as ex
from agents import planner as pl
from agents import researcher as rs
from agents.base import AgentRun
from env.tools import ToolBox
from tracing.trace import Tracer


@dataclass
class PipelineResult:
    task_input_id: str
    runs: dict[str, AgentRun] = field(default_factory=dict)
    findings: list[dict] = field(default_factory=list)      # as the researcher wrote them
    plan: list[dict] = field(default_factory=list)
    finding_events: dict[str, str] = field(default_factory=dict)
    step_events: dict[str, str] = field(default_factory=dict)


class Orchestrator:
    def __init__(self, task_id: str, ticket: str, llm, tools: ToolBox, tracer: Tracer, *, injector=None,
                 max_steps: int = 10, seed: int = 0, ops: bool = False):
        self.task_id, self.ticket = task_id, ticket
        self.llm, self.tools, self.tracer, self.injector = llm, tools, tracer, injector
        self.max_steps, self.seed, self.ops = max_steps, seed, ops

    def _agent(self, cls, **kw):
        return cls(self.llm, self.tools, self.tracer, max_steps=self.max_steps, seed=self.seed, **kw)

    def send(self, sender: str, receiver: str, items: list[dict], item_events: dict[str, str]) -> tuple[list[dict], dict[str, str]]:
        """Deliver items; returns (items as received, item id -> event id the receiver's copy came from)."""
        msg = self.tracer.log(sender, "message", {"from": sender, "to": receiver, "items": items},
                              list(item_events.values()) or [self._task_input])
        seen = dict(item_events)
        if self.injector is not None and hasattr(self.injector, "intercept_message"):
            delivered, fault = self.injector.intercept_message(sender, receiver, items)
            if fault:
                fe = self.tracer.log("harness", "fault_injected", fault, [msg["id"]])
                changed = set(fault.get("changed_ids") or [i["id"] for i in delivered])
                self.tracer.log(sender, "message", {"from": sender, "to": receiver, "items": delivered,
                                                    "delivered": True}, [fe["id"]])
                seen = {k: (fe["id"] if k in changed else v) for k, v in item_events.items()}
                items = delivered
        return items, seen

    def run(self) -> PipelineResult:
        start = self.tracer.log("harness", "message", {"task_input": True, "task_id": self.task_id,
                                                       "to": "researcher", "text": self.ticket})
        self._task_input = start["id"]
        result = PipelineResult(start["id"])

        # Researcher -> findings, each its own event.
        researcher = self._agent(rs.Researcher)
        r = researcher.run(rs.user_message(self.ticket), [start["id"]])
        result.runs["researcher"] = r
        result.findings = (r.final or {}).get("findings", [])
        for f in result.findings:
            parents = rs.finding_sources(f, r.tool_uses) or [r.final_llm_id]
            result.finding_events[f["id"]] = self.tracer.log("researcher", "finding", f, parents)["id"]

        # Researcher -> planner hand-off.
        findings, seen = self.send("researcher", "planner", result.findings, result.finding_events)
        planner = self._agent(pl.Planner, finding_ids=[f["id"] for f in findings])
        p = planner.run(pl.user_message(self.ticket, findings), list(seen.values()) or [start["id"]])
        result.runs["planner"] = p
        result.plan = (p.final or {}).get("steps", [])
        for s in result.plan:
            parents = [seen[u] for u in s.get("uses", []) if u in seen]
            parents += [result.step_events[a] for a in s.get("after", []) if a in result.step_events]
            result.step_events[s["id"]] = self.tracer.log("planner", "plan_step", s, parents or [p.final_llm_id])["id"]

        # Planner -> executor hand-off.
        steps, seen_steps = self.send("planner", "executor", result.plan, result.step_events)
        executor = self._agent(ex.Executor, step_events=seen_steps, can_run_scripts=self.ops)
        result.runs["executor"] = executor.run(ex.user_message(self.ticket, steps),
                                               list(seen_steps.values()) or [start["id"]])
        return result
