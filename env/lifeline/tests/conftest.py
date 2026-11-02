import shutil
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    """Every test works on its own copy of data/, so the real files are never touched."""
    copy = tmp_path / "data"
    shutil.copytree(DATA, copy)
    monkeypatch.setenv("LIFELINE_DATA_DIR", str(copy))
    return copy
