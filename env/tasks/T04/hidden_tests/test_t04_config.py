"""T04 answer key, settings part: cold regions (F13: marked `climate: cold`) get a winter_kit setting."""

from config.settings import load_regions


def test_cold_region_has_winter_kit_setting():
    assert load_regions()["HGL"].get("winter_kit") == {"people_per_kit": 3}


def test_other_regions_have_no_winter_kit_setting():
    regions = load_regions()
    assert "winter_kit" not in regions["NVL"]
    assert "winter_kit" not in regions["CPL"]


def test_existing_region_settings_unchanged():
    regions = load_regions()
    assert set(regions) == {"NVL", "CPL", "HGL"}
    assert {c: (r["name"], r["climate"]) for c, r in regions.items()} == {
        "NVL": ("North Valley", "temperate"), "CPL": ("Coastal Plains", "temperate"), "HGL": ("Highlands", "cold")}
