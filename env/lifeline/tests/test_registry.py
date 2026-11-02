import pytest

from registry.dedup import find_duplicates, same_family, soundex
from registry.register import get_household, load_households, next_household_id, register_household, set_status


def _record(**kw):
    rec = {"region": "CPL", "site": "SITE-CPL-A", "phone": "+999 71234567",
           "members": [{"name": "Lena Brook", "birth_date": "1991-02-03", "pregnant": False}]}
    return rec | kw


def test_register_assigns_next_id():
    expected = next_household_id()
    h = register_household(_record())
    assert h.id == expected
    assert get_household(h.id).head.name == "Lena Brook"


def test_register_rejects_duplicate_id_and_bad_region():
    existing = load_households()[0].id
    with pytest.raises(ValueError):
        register_household(_record(id=existing))
    with pytest.raises(ValueError):
        register_household(_record(region="ZZZ"))


def test_set_status():
    hid = load_households()[0].id
    set_status(hid, "merged", merged_into="HH-10427")
    assert get_household(hid).status == "merged"
    assert hid not in {h.id for h in load_households(active_only=True)}


def test_soundex():
    assert soundex("Robert") == soundex("Rupert") == "R163"
    assert soundex("Ashcraft") == "A261"
    assert soundex("Mohamed") == soundex("Muhammad")


def test_duplicates_found_by_sound_and_birth_year():
    hs = load_households()
    groups = find_duplicates(hs)
    assert groups
    by_id = {h.id: h for h in hs}
    for group in groups:
        a, b = by_id[group[0]], by_id[group[1]]
        assert same_family(a, b)
    # at least one duplicate is spelled differently, so exact matching would miss it
    assert any(by_id[g[0]].head.name != by_id[g[1]].head.name for g in groups)
