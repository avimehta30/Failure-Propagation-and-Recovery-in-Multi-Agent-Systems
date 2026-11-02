"""T01 answer key: household IDs are validated at registration (F5, weighted mod-11 check digit)."""

import pytest

from registry.register import load_households, register_household

# Valid IDs under the F5 rule (weights 5, 4, 3, 2), not used by any seed's registry.
NEW_VALID = ["HH-19992", "HH-19984", "HH-19976", "HH-19941"]
# Right shape, wrong check digit: the typos the ticket is about.
MISTYPED = ["HH-10471", "HH-19993", "HH-19980", "HH-00018"]
MALFORMED = ["HH-1042", "HH-104211", "HH-10A21", "hh-10421", "10421", ""]


def _record(hid=None):
    rec = {"region": "CPL", "site": "SITE-CPL-A", "phone": "+999 71234567",
           "members": [{"name": "Lena Brook", "birth_date": "1991-02-03", "pregnant": False}]}
    if hid is not None:
        rec["id"] = hid
    return rec


def _unused(ids):
    taken = {h.id for h in load_households()}
    return [i for i in ids if i not in taken]


@pytest.mark.parametrize("hid", NEW_VALID)
def test_valid_id_registers(hid):
    if hid not in _unused([hid]):
        pytest.skip("ID already used in this seed")
    assert register_household(_record(hid)).id == hid
    assert hid in {h.id for h in load_households()}


@pytest.mark.parametrize("hid", MISTYPED + MALFORMED)
def test_invalid_id_rejected_and_nothing_saved(hid):
    before = [h.id for h in load_households()]
    with pytest.raises(ValueError) as err:
        register_household(_record(hid))
    if hid:
        assert hid in str(err.value)
    assert [h.id for h in load_households()] == before


def test_automatic_id_still_works():
    h = register_household(_record())
    assert h.id in {x.id for x in load_households()}
