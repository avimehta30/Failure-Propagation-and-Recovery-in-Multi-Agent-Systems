"""General Lifeline settings: where the data lives, the operation clock, and feature flags.

Rules that differ by region (ration sizes, climate, cash amounts) live in regions.yaml,
not here. Use load_regions() / region() to read them.
"""

import os
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGIONS_FILE = Path(__file__).resolve().parent / "regions.yaml"

# Lifeline runs on a fixed operation clock so that plans, reports and payment
# rounds are reproducible. Override with LIFELINE_NOW for testing.
OPERATION_NOW = "2026-03-10T08:00:00"

# Relief items the warehouses stock, by product code (SKU).
SKUS = ("FOOD-KIT", "HYGIENE-KIT", "TARP")

FEATURES = {
    "sms_enabled": True,
    "cash_enabled": True,
}


def data_dir() -> Path:
    """Folder holding registry.json, ledger.json, network.json, audit.jsonl and outbox/."""
    return Path(os.environ.get("LIFELINE_DATA_DIR", ROOT / "data"))


def now() -> datetime:
    return datetime.fromisoformat(os.environ.get("LIFELINE_NOW", OPERATION_NOW))


def today() -> date:
    return now().date()


def load_regions() -> dict:
    with open(REGIONS_FILE) as f:
        return yaml.safe_load(f)["regions"]


def region(code: str) -> dict:
    regions = load_regions()
    if code not in regions:
        raise KeyError(f"unknown region {code!r}")
    return regions[code]


def region_codes() -> list[str]:
    return sorted(load_regions())


def feature(name: str) -> bool:
    return FEATURES.get(name, False)
