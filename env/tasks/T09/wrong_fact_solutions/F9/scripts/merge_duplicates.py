"""Ops script: merge duplicate household registrations. CHANGES data/registry.json.

Built on the wrong F9: duplicates are households whose head has exactly the same name.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ids import is_valid_household_id  # noqa: E402
from registry.register import load_households, set_status  # noqa: E402


def main() -> None:
    groups = {}
    for h in sorted(load_households(active_only=True), key=lambda h: h.id):
        groups.setdefault((h.head.name, h.head.birth_year), []).append(h.id)
    for group in groups.values():
        if len(group) < 2:
            continue
        valid = [hid for hid in group if is_valid_household_id(hid)]
        keep = valid[0] if valid else group[0]
        for hid in group:
            if hid != keep:
                set_status(hid, "merged", merged_into=keep)


if __name__ == "__main__":
    main()
