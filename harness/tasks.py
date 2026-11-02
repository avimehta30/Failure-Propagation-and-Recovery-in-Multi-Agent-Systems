"""Loading tasks and building their workspaces.

A task folder (env/tasks/T01/) holds prompt.txt, starter.json, meta.json, the answer key
(hidden_tests/ or expected_state/), reference_solution/ and wrong_fact_solutions/<fact>/.
Solutions are overlays: files laid over the workspace at the same relative paths.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIFELINE = ROOT / "env" / "lifeline"
TASKS = ROOT / "env" / "tasks"


@dataclass(frozen=True)
class Task:
    id: str
    dir: Path
    prompt: str
    starter: dict
    meta: dict

    @property
    def hidden_tests(self) -> Path:
        return self.dir / "hidden_tests"

    @property
    def reference_solution(self) -> Path:
        return self.dir / "reference_solution"

    def wrong_fact_solutions(self) -> dict[str, Path]:
        base = self.dir / "wrong_fact_solutions"
        return {p.name: p for p in sorted(base.iterdir()) if p.is_dir()} if base.exists() else {}


def all_task_ids() -> list[str]:
    return sorted(p.name for p in TASKS.iterdir() if (p / "meta.json").exists())


def load_task(task_id: str) -> Task:
    d = TASKS / task_id
    return Task(task_id, d, (d / "prompt.txt").read_text(), json.loads((d / "starter.json").read_text()),
                json.loads((d / "meta.json").read_text()))


def make_workspace(task: Task, dest: Path, seed: int | None = None) -> Path:
    """Fresh copy of Lifeline at the task's starting commit, with the seed's data."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(LIFELINE), "archive", task.starter["lifeline_commit"]],
                             capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest)
    seed = task.starter["seed"] if seed is None else seed
    if seed != 0:
        from env.seed_data import write
        write(dest / "data", seed)
    return dest


def overlay(src: Path, workspace: Path) -> list[str]:
    """Copy every file under `src` into the workspace at the same relative path."""
    written = []
    for p in sorted(Path(src).rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            target = Path(workspace) / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
            written.append(str(p.relative_to(src)))
    return written
