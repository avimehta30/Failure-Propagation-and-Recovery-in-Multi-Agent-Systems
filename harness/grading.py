"""Grading a finished workspace with a task's hidden tests (code tasks T01-T08).

The hidden tests are copied to a temporary folder outside the workspace and run with the
workspace on the import path, so they test the workspace's code against a copy of its data.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from harness.tasks import Task


def run_hidden_tests(task: Task, workspace: Path, timeout_s: int = 120) -> dict:
    workspace = Path(workspace).resolve()
    with tempfile.TemporaryDirectory(prefix=f"grade_{task.id}_") as tmp:
        tests = Path(tmp) / "hidden_tests"
        shutil.copytree(task.hidden_tests, tests, ignore=shutil.ignore_patterns("__pycache__"))
        report = Path(tmp) / "report.xml"
        env = os.environ | {"PYTHONPATH": str(workspace), "LIFELINE_WORKSPACE": str(workspace),
                            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("LIFELINE_DATA_DIR", None)
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", os.devnull,
                               "--rootdir", tmp, f"--junitxml={report}", str(tests)],
                              cwd=tmp, env=env, capture_output=True, text=True, timeout=timeout_s)
        results = _per_test(report) if report.exists() else {}
    n_passed = sum(r == "passed" for r in results.values())
    return {"passed": proc.returncode == 0 and bool(results) and n_passed == len(results),
            "test_results": results, "n_passed": n_passed, "n_failed": len(results) - n_passed,
            "output": proc.stdout[-4000:] + proc.stderr[-1000:]}


def _per_test(report: Path) -> dict[str, str]:
    out = {}
    for case in ET.parse(report).iter("testcase"):
        name = f"{case.get('classname', '').split('.')[-1]}::{case.get('name')}"
        failed = any(child.tag in ("failure", "error") for child in case)
        skipped = any(child.tag == "skipped" for child in case)
        out[name] = "failed" if failed else "skipped" if skipped else "passed"
    return out
