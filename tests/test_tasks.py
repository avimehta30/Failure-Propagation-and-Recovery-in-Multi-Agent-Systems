"""Task sanity checks from design.md Section 9 that need no LLM:

1. the reference solution passes the hidden tests,
2. a solution built on each wrong fact the task depends on fails,
plus: the starting code fails (the ticket is not already done) and the reference
solution keeps Lifeline's own visible tests passing.
"""

import json
import os
import subprocess
import sys

import pytest

from harness.grading import run_hidden_tests
from harness.ops import apply_solution, build_expected_state, expected_dir, grade_ops
from harness.tasks import ROOT, all_task_ids, load_task, make_workspace, overlay

FACTS = json.loads((ROOT / "env" / "facts.json").read_text())
TASKS = all_task_ids()
SEEDS = [0, 1, 2]


def _grade(task, tmp_path, solution=None, seed=0):
    ws = make_workspace(task, tmp_path / "workspace", seed=seed)
    if task.meta["kind"] == "ops":
        if solution is not None:
            apply_solution(task, ws, solution)
        return grade_ops(task, ws, seed)
    if solution is not None:
        overlay(solution, ws)
    return run_hidden_tests(task, ws)


def test_all_eight_tasks_exist():
    assert set(TASKS) == {"T01", "T02", "T03", "T04", "T05", "T09", "T10", "T11"}


@pytest.mark.parametrize("task_id", TASKS)
def test_task_files(task_id):
    task = load_task(task_id)
    answer_key = [expected_dir(task, s) for s in SEEDS] if task.meta["kind"] == "ops" else [task.hidden_tests]
    assert task.prompt.strip() and task.reference_solution.is_dir() and all(p.is_dir() for p in answer_key)
    assert task.starter["lifeline_commit"] == FACTS["lifeline_start_commit"]
    for fid, files in task.meta["facts"].items():
        assert FACTS["facts"][fid]["tasks"][task_id] == files, f"{task_id} {fid} disagrees with facts.json"
    assert set(task.wrong_fact_solutions()) == set(task.meta["facts"]), "one wrong-fact solution per fact"
    assert set(overlay_paths(task.reference_solution)) <= set(task.meta["target_files"])


def overlay_paths(src):
    return [str(p.relative_to(src)) for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("task_id", TASKS)
def test_starter_fails(task_id, seed, tmp_path):
    assert not _grade(load_task(task_id), tmp_path, seed=seed)["passed"]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("task_id", TASKS)
def test_reference_passes(task_id, seed, tmp_path):
    task = load_task(task_id)
    result = _grade(task, tmp_path, task.reference_solution, seed=seed)
    assert result["passed"], result["output"]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("task_id", TASKS)
def test_wrong_fact_solutions_fail(task_id, seed, tmp_path):
    task = load_task(task_id)
    for fid, solution in task.wrong_fact_solutions().items():
        result = _grade(task, tmp_path / fid, solution, seed=seed)
        assert not result["passed"], f"{task_id}: solution built on wrong {fid} still passes"


@pytest.mark.parametrize("task_id", TASKS)
def test_reference_keeps_visible_tests_passing(task_id, tmp_path):
    task = load_task(task_id)
    ws = make_workspace(task, tmp_path / "workspace")
    overlay(task.reference_solution, ws)
    env = os.environ | {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("LIFELINE_DATA_DIR", None)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ws, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]


@pytest.mark.parametrize("task_id", [t for t in TASKS if load_task(t).meta["kind"] == "ops"])
def test_expected_state_is_what_the_reference_produces(task_id, tmp_path):
    """expected_state/ must be exactly what the reference solution's scripts produce."""
    task = load_task(task_id)
    stored = {s: {n: (expected_dir(task, s) / n).read_text() for n in task.meta["compare"]} for s in SEEDS}
    try:
        build_expected_state(task)
        rebuilt = {s: {n: (expected_dir(task, s) / n).read_text() for n in task.meta["compare"]} for s in SEEDS}
    finally:
        for s in SEEDS:
            for n, text in stored[s].items():
                (expected_dir(task, s) / n).write_text(text)
    assert rebuilt == stored
