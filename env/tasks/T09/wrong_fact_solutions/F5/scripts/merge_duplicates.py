"""Ops script: merge duplicate household registrations. CHANGES data/registry.json.

Built on the wrong F5: any HH- plus five digits is a valid ID, so every ID in a group looks
valid and the first (lowest) ID is kept.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registry.dedup import find_duplicates  # noqa: E402
from registry.register import load_households, set_status  # noqa: E402


def looks_valid(hid: str) -> bool:
    return re.fullmatch(r"HH-\d{5}", hid) is not None


def main() -> None:
    for group in find_duplicates(load_households()):
        valid = [hid for hid in group if looks_valid(hid)]
        keep = valid[0] if valid else group[0]
        for hid in group:
            if hid != keep:
                set_status(hid, "merged", merged_into=keep)


if __name__ == "__main__":
    main()
