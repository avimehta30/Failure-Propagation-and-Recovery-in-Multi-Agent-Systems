import os
import shutil
from pathlib import Path

import pytest

WORKSPACE = Path(os.environ["LIFELINE_WORKSPACE"])


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    """Each hidden test runs against its own copy of the workspace's data/."""
    copy = tmp_path / "data"
    shutil.copytree(WORKSPACE / "data", copy)
    monkeypatch.setenv("LIFELINE_DATA_DIR", str(copy))
    return copy
