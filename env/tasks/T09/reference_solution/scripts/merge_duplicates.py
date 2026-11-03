"""Ops script: merge duplicate household registrations. CHANGES data/registry.json.

Run once from the Lifeline root:  python scripts/merge_duplicates.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ids import is_valid_household_id  # noqa: E402
from registry.dedup import find_duplicates  # noqa: E402
from registry.register import load_households, set_status  # noqa: E402


def main() -> None:
    for group in find_duplicates(load_households()):
        valid = [hid for hid in group if is_valid_household_id(hid)]
        keep = valid[0] if valid else group[0]
        for hid in group:
            if hid != keep:
                set_status(hid, "merged", merged_into=keep)
                print(f"merged {hid} into {keep}")


if __name__ == "__main__":
    main()
