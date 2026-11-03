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
from agents import verifier as vf
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
    verification: dict | None = None                       # always-verify baseline only


class Orchestrator:
    def __init__(self, task_id: str, ticket: str, llm, tools: ToolBox, tracer: Tracer, *, injector=None,
                 max_steps: int = 10, seed: int = 0, ops: bool = False, keep_full_results: int | None = 2,
                 verify: bool = False, verifier_steps: int = 6):
        self.task_id, self.ticket = task_id, ticket
        self.llm, self.tools, self.tracer, self.injector = llm, tools, tracer, injector
        self.max_steps, self.seed, self.ops = max_steps, seed, ops
        self.keep_full_results = keep_full_results
        self.verify, self.verifier_steps = verify, verifier_steps
        self.vstats = {"checked": 0, "rejected": 0, "redone": 0, "verdicts": [], "llm_calls": 0,
                       "tokens_in": 0, "tokens_out": 0, "latency_ms": 0.0,
                       "redo_llm_calls": 0, "redo_tokens": 0}

    def _agent(self, cls, **kw):
        return cls(self.llm, self.tools, self.tracer, max_steps=self.max_steps, seed=self.seed,
                   keep_full_results=self.keep_full_results, **kw)

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
        if self.verify:
            findings, seen = self._verify_findings(findings, seen)
        planner = self._agent(pl.Planner, finding_ids=[f["id"] for f in findings])
        p = planner.run(pl.user_message(self.ticket, findings), list(seen.values()) or [start["id"]])
        result.runs["planner"] = p
        result.plan = (p.final or {}).get("steps", [])
        for s in result.plan:
            parents = [seen[u] for u in s.get("uses", []) if u in seen]
            parents += [result.step_events[a] for a in s.get("after", []) if a in result.step_events]
            result.step_events[s["id"]] = self.tracer.log("planner", "plan_step", s, parents or [p.final_llm_id])["id"]

        if self.verify:
            self._verify_steps(result, findings, seen)
            self.tools.gate = self._edit_gate(result.plan)

        # Planner -> executor hand-off.
        steps, seen_steps = self.send("planner", "executor", result.plan, result.step_events)
        step_files: dict[str, list[str]] = {}
        for s in steps:
            step_files.setdefault(str(s.get("file", "")).strip().lstrip("./"), []).append(s["id"])
        executor = self._agent(ex.Executor, step_events=seen_steps, step_files=step_files, can_run_scripts=self.ops)
        result.runs["executor"] = executor.run(ex.user_message(self.ticket, steps),
                                               list(seen_steps.values()) or [start["id"]])
        if self.verify:
            self.tools.gate = None
            result.verification = self.vstats
        return result

    # ------------------------------------------------------------------ always-verify baseline
    def _check(self, kind: str, item_id: str, item_event: str, message: str) -> tuple[str, str, str]:
        v = self._agent(vf.Verifier)
        v.max_steps = self.verifier_steps
        run = v.run(message, [item_event])
        final = run.final or {"verdict": "accept", "reason": "no verdict within the step budget"}
        ev = self.tracer.log("verifier", "message", {"kind": kind, "item": item_id, "verdict": final["verdict"],
                                                     "reason": final.get("reason", "")},
                             [run.final_llm_id or item_event])
        st = self.vstats
        st["checked"] += 1
        st["rejected"] += final["verdict"] == "reject"
        st["llm_calls"] += run.steps
        st["tokens_in"] += run.tokens_in
        st["tokens_out"] += run.tokens_out
        st["latency_ms"] += run.latency_ms
        st["verdicts"].append({"kind": kind, "item": item_id, "verdict": final["verdict"], "event": ev["id"]})
        return final["verdict"], final.get("reason", ""), ev["id"]

    def _count_redo(self, run: AgentRun) -> None:
        self.vstats["redone"] += 1
        self.vstats["redo_llm_calls"] += run.steps
        self.vstats["redo_tokens"] += run.tokens_in + run.tokens_out

    def _verify_findings(self, findings: list[dict], seen: dict[str, str]):
        findings, seen = list(findings), dict(seen)
        for i, f in enumerate(findings):
            verdict, reason, vid = self._check("finding", f["id"], seen[f["id"]], vf.finding_message(self.ticket, f))
            if verdict != "reject":
                continue
            r = self._agent(rs.Researcher).run(rs.redo_message(self.ticket, f, reason), [vid])
            self._count_redo(r)
            got = (r.final or {}).get("findings") or []
            new = next((x for x in got if x.get("id") == f["id"]), got[0] if got else None)
            if new:
                new = dict(new, id=f["id"])
                parents = rs.finding_sources(new, r.tool_uses) + [vid]
                seen[f["id"]] = self.tracer.log("researcher", "finding", dict(new, redone=True), parents)["id"]
                findings[i] = new
        return findings, seen

    def _verify_steps(self, result: PipelineResult, findings: list[dict], seen: dict[str, str]) -> None:
        for i, s in enumerate(list(result.plan)):
            verdict, reason, vid = self._check("plan_step", s["id"], result.step_events[s["id"]],
                                               vf.step_message(self.ticket, s, findings))
            if verdict != "reject":
                continue
            planner = self._agent(pl.Planner, finding_ids=[f["id"] for f in findings],
                                  prior_steps=[x["id"] for x in result.plan[:i]])
            p = planner.run(pl.redo_message(self.ticket, findings, result.plan, s, reason), [vid])
            self._count_redo(p)
            got = (p.final or {}).get("steps") or []
            new = next((x for x in got if x.get("id") == s["id"]), got[0] if got else None)
            if new:
                new = dict(new, id=s["id"])
                parents = [seen[u] for u in new.get("uses", []) if u in seen]
                parents += [result.step_events[a] for a in new.get("after", []) if a in result.step_events]
                result.step_events[s["id"]] = self.tracer.log("planner", "plan_step", dict(new, redone=True),
                                                              parents + [vid])["id"]
                result.plan[i] = new

    def _edit_gate(self, plan: list[dict]):
        """Review each proposed write before it is applied; a path is rejected at most once."""
        by_id = {s["id"]: s for s in plan}
        by_file = {str(s.get("file", "")).strip().lstrip("./"): s for s in plan}
        rejected_once: set[str] = set()

        def gate(agent, tool, args, call_id):
            if agent != "executor" or tool != "write_file" or not isinstance(args.get("content"), str):
                return None
            path = str(args.get("path", "")).strip().lstrip("./")
            if path in rejected_once:
                return None
            step = by_id.get(str(args.get("step", ""))) or by_file.get(path)
            verdict, reason, _ = self._check("file_edit", path, call_id,
                                             vf.edit_message(self.ticket, step, path, args["content"]))
            if verdict == "reject":
                rejected_once.add(path)
                return reason
            return None
        return gate
