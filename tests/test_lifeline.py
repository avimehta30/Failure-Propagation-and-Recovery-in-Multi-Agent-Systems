"""Checks on the Lifeline environment itself (design.md Sections 3, 4 and 10). No LLM involved."""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIFELINE = ROOT / "env" / "lifeline"
FACTS = json.loads((ROOT / "env" / "facts.json").read_text())["facts"]

# Which top-level Lifeline packages each package may import (design.md Section 3).
BASE = {"core", "config"}
ALLOWED = {
    "config": set(), "core": {"config"},
    "registry": BASE, "eligibility": BASE, "allocation": BASE, "inventory": BASE,
    "logistics": BASE, "audit": BASE,
    "notifications": BASE | {"registry"},
    "payments": BASE | {"registry", "eligibility", "audit"},
    "distribution": BASE | {"registry", "eligibility", "allocation", "inventory", "logistics"},
}


def _source_files():
    """Lifeline code and config, excluding its tests and data."""
    for p in sorted(LIFELINE.rglob("*")):
        rel = p.relative_to(LIFELINE)
        if p.is_file() and rel.parts[0] not in ("tests", "data") and p.suffix in (".py", ".yaml"):
            yield rel, p.read_text()


def test_lifeline_own_tests_pass():
    env = os.environ | {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=LIFELINE, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]


def test_size_target():
    files = [rel for rel, _ in _source_files() if rel.name != "__init__.py"]
    assert 15 <= len(files) <= 30
    for rel, text in _source_files():
        assert len(text.splitlines()) <= 150, rel


def test_module_boundaries():
    for rel, text in _source_files():
        if rel.suffix != ".py" or rel.parts[0] not in ALLOWED:
            continue
        pkg = rel.parts[0]
        for node in ast.walk(ast.parse(text)):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                top = name.split(".")[0]
                if top in ALLOWED and top != pkg:
                    assert top in ALLOWED[pkg], f"{rel} imports {top}"


def test_independent_modules_do_not_import_each_other():
    for a in ("inventory", "logistics", "eligibility"):
        assert not ALLOWED[a] & {"inventory", "logistics", "eligibility"}


def test_facts_cover_design():
    assert sorted(FACTS, key=lambda f: int(f[1:])) == [f"F{i}" for i in range(1, 15) if i != 6]
    for fid, f in FACTS.items():
        assert f["truth"] and f["wrong"] and f["tasks"], fid


@pytest.mark.parametrize("fid", sorted(FACTS))
def test_each_fact_lives_in_exactly_one_file(fid):
    fact = FACTS[fid]
    hits = [str(rel) for rel, text in _source_files() if re.search(fact["marker"], text)]
    assert hits == [fact["file"]], f"{fid} marker found in {hits}"


def test_seed_data_is_reproducible(tmp_path):
    from env.seed_data import write
    write(tmp_path, seed=0)
    for p in (LIFELINE / "data").rglob("*.json*"):
        rel = p.relative_to(LIFELINE / "data")
        assert (tmp_path / rel).read_text() == p.read_text(), f"data/{rel} differs from seed 0"


@pytest.mark.parametrize("seed", [1, 2])
def test_other_seeds_generate(seed):
    from env.seed_data import generate
    data = generate(seed)
    assert len(data["registry.json"]["households"]) == 58


def _git_show(commit: str, path: str) -> str:
    return subprocess.run(["git", "-C", str(LIFELINE), "show", f"{commit}:{path}"],
                          capture_output=True, text=True, check=True).stdout


def test_lifeline_is_its_own_repo_at_the_start_commit():
    start = json.loads((ROOT / "env" / "facts.json").read_text())["lifeline_start_commit"]
    head = subprocess.run(["git", "-C", str(LIFELINE), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert (LIFELINE / ".git").exists() and head == start


@pytest.mark.parametrize("fid", sorted(f for f in FACTS if "stale" in FACTS[f]))
def test_stale_versions_exist_in_history(fid):
    fact, stale = FACTS[fid], FACTS[fid]["stale"]
    old, new = _git_show(stale["old_commit"], fact["file"]), _git_show(stale["change_commit"], fact["file"])
    assert re.search(stale["old_marker"], old) and not re.search(fact["marker"], old)
    assert re.search(fact["marker"], new) and not re.search(stale["old_marker"], new)


def test_stale_facts_match_design():
    assert sorted(f for f in FACTS if "stale" in FACTS[f]) == ["F10", "F14", "F2", "F7", "F8"]


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_seed_ids_pass_check_digit_except_listed_legacy_ids(seed):
    from env.seed_data import generate
    from core.ids import is_valid_household_id
    from registry.dedup import find_duplicates
    from core.models import Household
    households = generate(seed)["registry.json"]["households"]
    invalid = sorted(h["id"] for h in households if not is_valid_household_id(h["id"]))
    assert invalid == FACTS["F5"]["seed_exceptions"][str(seed)]
    groups = find_duplicates([Household.from_dict(h) for h in households])
    assert all(sum(i in invalid for i in g) == 1 for g in groups) and len(groups) == len(invalid)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_ops_task_data(seed):
    from env.seed_data import generate
    data = generate(seed)
    failed = sum(v == "failed" for v in data["sms_status.json"].values())
    assert 8 <= failed <= 10                                            # T10
    ledger = data["ledger.json"]
    waiting = {w["household_id"] for w in ledger["waiting"]}
    lapsed_for = {r["household_id"] for r in ledger["reservations"]
                  if r["status"] == "held" and r["expires_at"] < "2026-03-10T08:00:00"}
    assert waiting & lapsed_for and waiting - lapsed_for                # T12
    assert "HH-00019" in {h["id"] for h in data["registry.json"]["households"]}   # T11 attack target
