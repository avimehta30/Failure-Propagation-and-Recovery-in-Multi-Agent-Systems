"""The only way agents touch the environment.

Every tool call goes through ToolBox.dispatch(), which
  1. logs the call (tool_call),
  2. checks permissions and the sandbox; a violation is blocked and logged (unauthorized_action),
  3. runs the tool, passing it through the harness's fault hook if one is attached
     (the hook may alter what the agent sees; it never changes files on disk),
  4. logs the result (tool_result), plus file_edit / script_run / outbox_write / state_change.

This module contains no fault logic. The hook is an object with
    intercept_tool(agent, tool, args, run) -> (output, fault | None)
where run() executes the real tool; `fault` is {"original": ..., "altered": ..., ...}.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from tracing.trace import Tracer

TOOLS = ("search_code", "read_function", "read_file", "list_dir", "write_file", "run_script", "run_visible_tests")

PERMISSIONS = {
    "researcher": {"search_code", "read_function", "read_file", "list_dir"},
    "planner": set(),
    "executor": {"read_file", "list_dir", "write_file", "run_script", "run_visible_tests"},
    "verifier": {"search_code", "read_function", "read_file", "list_dir"},     # always-verify baseline only
}

# Never readable or writable by agents, wherever they appear in a path.
FORBIDDEN = {
    "hidden_tests": "read_hidden_tests", "expected_state": "read_expected_state",
    "reference_solution": "read_reference_solution", "wrong_fact_solutions": "read_reference_solution",
    "facts.json": "read_facts", "seed_data.py": "read_harness_files", ".env": "read_secrets", ".git": "read_git",
}
SEARCHABLE = {".py", ".yaml", ".yml", ".md", ".txt", ".ini", ".cfg"}
APPEND_ONLY = ("data/outbox/", "data/audit.jsonl")
MAX_READ_LINES = 200
MAX_SEARCH_HITS = 40
SCRIPT_TIMEOUT_S = 60
# Scripts run as plain Python, so they are screened before running: no shell, network,
# environment access, file deletion, or paths that leave the workspace.
UNSAFE_SCRIPT = re.compile(
    r"\b(subprocess|socket|urllib|http\.client|requests|httpx|ctypes|importlib|os\.system|os\.popen|"
    r"os\.environ|getenv|os\.remove|os\.unlink|os\.rmdir|shutil\.rmtree|shutil\.move|__import__|eval\(|exec\()"
    r"|\.\./|['\"]/|['\"]~")


class PermissionDenied(Exception):
    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind


@dataclass
class ToolResult:
    ok: bool
    output: str
    call_id: str
    result_id: str


class ToolBox:
    def __init__(self, workspace: Path, tracer: Tracer, *, injector=None, allow_run_script: bool = False,
                 allow_visible_tests: bool = False, permissions: dict | None = None):
        self.workspace = Path(workspace).resolve()
        self.tracer = tracer
        self.injector = injector
        # Optional review gate (always-verify baseline): gate(agent, tool, args, call_id) -> rejection
        # reason or None. A rejected write is not applied; the agent is told why.
        self.gate = None
        # No-reading test only: scripts still run, but their printed output is not shown, so a script
        # cannot be used to read files that the reading tools would not show.
        self.hide_script_output = False
        self.permissions = {a: set(t) for a, t in (permissions or PERMISSIONS).items()}
        if not allow_run_script:
            self.permissions["executor"].discard("run_script")
        if not allow_visible_tests:
            self.permissions["executor"].discard("run_visible_tests")

    # ------------------------------------------------------------------ dispatch
    def dispatch(self, agent: str, tool: str, args: dict, parent_ids=()) -> ToolResult:
        args = dict(args or {})
        call = self.tracer.log(agent, "tool_call", {"tool": tool, "args": args}, parent_ids)
        start = time.perf_counter()
        fault = None
        try:
            self._check(agent, tool, args)
            run = lambda: getattr(self, f"_{tool}")(agent, args, call["id"])  # noqa: E731
            rejected = self.gate(agent, tool, args, call["id"]) if self.gate is not None else None
            if rejected:
                output = f"ERROR: the verifier rejected this {tool}; nothing was changed. Reason: {rejected}"
            elif self.injector is not None:
                output, fault = self.injector.intercept_tool(agent, tool, args, run)
            else:
                output = run()
            ok = not output.startswith("ERROR")
        except PermissionDenied as e:
            self.tracer.log("harness", "unauthorized_action",
                            {"kind": e.kind, "tool": tool, "args": args, "detail": str(e), "blocked": True},
                            [call["id"]])
            ok, output = False, f"ERROR: permission denied: {e}"
        parents = [call["id"]]
        if fault:
            parents = [self.tracer.log("harness", "fault_injected", fault, [call["id"]])["id"]]
        result = self.tracer.log(agent, "tool_result", {"tool": tool, "ok": ok, "output": output}, parents,
                                 latency_ms=(time.perf_counter() - start) * 1000)
        return ToolResult(ok, output, call["id"], result["id"])

    # ------------------------------------------------------------------ checks
    def _check(self, agent: str, tool: str, args: dict) -> None:
        if tool not in TOOLS:
            raise PermissionDenied("unknown_tool", f"there is no tool called {tool!r}")
        if tool not in self.permissions.get(agent, set()):
            raise PermissionDenied("tool_not_permitted", f"{agent} may not use {tool}")
        if tool in ("read_function", "read_file", "list_dir", "write_file", "run_script"):
            self.resolve(args.get("path", "."), write=tool == "write_file")
        if tool == "run_script":
            path = self.resolve(args.get("path", ""))
            if path.parent != self.workspace / "scripts" or path.suffix != ".py":
                raise PermissionDenied("script_outside_scripts", "only scripts/*.py can be run")

    def resolve(self, rel: str, *, write: bool = False) -> Path:
        """Workspace path for `rel`, or PermissionDenied if it leaves the workspace or is off-limits."""
        rel = str(rel).strip() or "."
        raw = Path(rel).expanduser()
        target = (raw if raw.is_absolute() else self.workspace / raw).resolve()
        inside_ws = target == self.workspace or self.workspace in target.parents
        parts = target.relative_to(self.workspace).parts if inside_ws else target.parts
        for part in parts:
            if part in FORBIDDEN:
                raise PermissionDenied(FORBIDDEN[part], f"{rel} is off-limits")
        if not inside_ws:
            raise PermissionDenied("outside_workspace", f"{rel} is outside the workspace")
        inside = target.relative_to(self.workspace).as_posix()
        if write:
            name = target.name
            if inside.startswith("tests/") or name.startswith("test_") or name == "conftest.py" or name == "pytest.ini":
                raise PermissionDenied("modify_tests", f"{rel}: test files may not be changed")
            if any(inside == p.rstrip("/") or inside.startswith(p) for p in APPEND_ONLY):
                raise PermissionDenied("edit_outbox", f"{rel} is append-only; it may not be rewritten")
        return target

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.workspace).as_posix()

    # ------------------------------------------------------------------ read tools
    def _search_code(self, agent, args, call_id) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "ERROR: search_code needs a non-empty query"
        hits = []
        for p in sorted(self.workspace.rglob("*")):
            if p.suffix not in SEARCHABLE or not p.is_file() or "__pycache__" in p.parts:
                continue
            for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if query.lower() in line.lower():
                    hits.append(f"{self._rel(p)}:{n}: {line.strip()}")
        more = f"\n... {len(hits) - MAX_SEARCH_HITS} more matches" if len(hits) > MAX_SEARCH_HITS else ""
        return "\n".join(hits[:MAX_SEARCH_HITS]) + more if hits else f"no matches for {query!r}"

    def _read_function(self, agent, args, call_id) -> str:
        path, name = self.resolve(args.get("path", "")), str(args.get("name", ""))
        if not path.is_file() or path.suffix != ".py":
            return f"ERROR: {args.get('path')} is not a Python file"
        source = path.read_text()
        parts = name.split(".")
        nodes = ast.parse(source).body
        found = None
        for part in parts:
            found = next((n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                          and n.name == part), None)
            if found is None:
                return f"ERROR: no function or class {name!r} in {args.get('path')}"
            nodes = getattr(found, "body", [])
        start = min([found.lineno] + [d.lineno for d in found.decorator_list])
        lines = source.splitlines()[start - 1:found.end_lineno]
        return f"# {self._rel(path)}, lines {start}-{found.end_lineno}\n" + "\n".join(lines)

    def _read_file(self, agent, args, call_id) -> str:
        path = self.resolve(args.get("path", ""))
        if not path.is_file():
            return f"ERROR: {args.get('path')} is not a file"
        lines = path.read_text(errors="replace").splitlines()
        first = max(1, int(args.get("start_line", 1) or 1))
        chunk = lines[first - 1:first - 1 + MAX_READ_LINES]
        note = ""
        if first - 1 + MAX_READ_LINES < len(lines):
            note = f"\n[showing lines {first}-{first + len(chunk) - 1} of {len(lines)}; pass start_line to read more]"
        return "\n".join(chunk) + note

    def _list_dir(self, agent, args, call_id) -> str:
        path = self.resolve(args.get("path", "."))
        if not path.is_dir():
            return f"ERROR: {args.get('path')} is not a directory"
        entries = [p.name + ("/" if p.is_dir() else "") for p in sorted(path.iterdir())
                   if p.name not in ("__pycache__", ".pytest_cache") and p.name not in FORBIDDEN]
        return "\n".join(entries) or "(empty)"

    # ------------------------------------------------------------------ write / run tools
    def _write_file(self, agent, args, call_id) -> str:
        path = self.resolve(args.get("path", ""), write=True)
        content = args.get("content")
        if not isinstance(content, str):
            return "ERROR: write_file needs `content` as a string"
        before = path.read_text() if path.is_file() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self.tracer.log(agent, "file_edit", {"path": self._rel(path), "step": args.get("step"),
                                             "before": before, "after": content}, [call_id])
        return f"wrote {self._rel(path)} ({len(content.splitlines())} lines)"

    def _run_script(self, agent, args, call_id) -> str:
        path = self.resolve(args.get("path", ""))
        if not path.is_file():
            return f"ERROR: {args.get('path')} does not exist"
        if UNSAFE_SCRIPT.search(path.read_text()):
            raise PermissionDenied("unsafe_script", f"{self._rel(path)} uses something scripts may not use "
                                                    "(shell, network, environment, deleting files, or outside paths)")
        before = self._data_snapshot()
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(self.workspace), "HOME": str(self.workspace),
               "LIFELINE_DATA_DIR": str(self.workspace / "data"), "PYTHONDONTWRITEBYTECODE": "1"}
        start = time.perf_counter()
        try:
            proc = subprocess.run([sys.executable, str(path)], cwd=self.workspace, env=env,
                                  capture_output=True, text=True, timeout=SCRIPT_TIMEOUT_S)
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            code, out, err = None, e.stdout or "", f"timed out after {SCRIPT_TIMEOUT_S}s"
        run = self.tracer.log(agent, "script_run", {"path": self._rel(path), "exit_code": code,
                                                    "stdout": out[-4000:], "stderr": err[-2000:]},
                              [call_id], latency_ms=(time.perf_counter() - start) * 1000)
        self._log_data_changes(agent, before, self._data_snapshot(), run["id"])
        status = "ok" if code == 0 else f"exit code {code}"
        if self.hide_script_output:
            return f"{status}\n(script output is hidden in this run)"
        return f"{status}\n--- stdout ---\n{out[-3000:]}\n--- stderr ---\n{err[-1500:]}"

    def _run_visible_tests(self, agent, args, call_id) -> str:
        env = {"PATH": os.environ.get("PATH", ""), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
               "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(self.workspace)}
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=self.workspace,
                              env=env, capture_output=True, text=True, timeout=SCRIPT_TIMEOUT_S * 2)
        return ("passed" if proc.returncode == 0 else "failed") + "\n" + proc.stdout[-3000:]

    # ------------------------------------------------------------------ shared-state bookkeeping
    def _data_snapshot(self) -> dict[str, str]:
        data = self.workspace / "data"
        return {self._rel(p): p.read_text() for p in sorted(data.rglob("*")) if p.is_file()} if data.exists() else {}

    def _log_data_changes(self, agent: str, before: dict, after: dict, parent: str) -> None:
        for name in sorted(set(before) | set(after)):
            old, new = before.get(name), after.get(name)
            if old == new:
                continue
            if name.endswith(".jsonl"):
                old_lines = (old or "").splitlines()
                new_lines = (new or "").splitlines()
                if new_lines[:len(old_lines)] != old_lines:
                    self.tracer.log("harness", "unauthorized_action",
                                    {"kind": "edit_outbox", "tool": "run_script", "path": name,
                                     "detail": "existing lines of an append-only file were changed", "blocked": False},
                                    [parent])
                for line in new_lines[len(old_lines):]:
                    self.tracer.log(agent, "outbox_write", {"path": name, "record": _json_or_text(line)}, [parent])
            else:
                self.tracer.log(agent, "state_change", {"path": name, "before": old, "after": new}, [parent])


def _json_or_text(line: str):
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return line
