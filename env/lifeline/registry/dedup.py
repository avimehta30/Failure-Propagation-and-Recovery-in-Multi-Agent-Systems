"""Finding families that registered more than once.

Names are often written down differently at different registration desks, so two
records are treated as the same family when the head of household's name SOUNDS the
same (Soundex code of every part of the name) and the head's birth year matches.
"""

from core.models import Household

_CODES = {c: d for letters, d in (("bfpv", "1"), ("cgjkqsxz", "2"), ("dt", "3"),
                                  ("l", "4"), ("mn", "5"), ("r", "6")) for c in letters}


def soundex(word: str) -> str:
    """American Soundex: first letter plus three digits, e.g. 'Robert' -> 'R163'."""
    letters = [c for c in word.lower() if c.isalpha()]
    if not letters:
        return ""
    out = letters[0].upper()
    last = _CODES.get(letters[0], "")
    for c in letters[1:]:
        code = _CODES.get(c, "")
        if code and code != last:
            out += code
        if c not in "hw":          # h and w do not separate letters with the same code
            last = code
    return (out + "000")[:4]


def name_key(name: str) -> tuple[str, ...]:
    return tuple(soundex(part) for part in name.split())


def same_family(a: Household, b: Household) -> bool:
    return (name_key(a.head.name) == name_key(b.head.name)
            and a.head.birth_year == b.head.birth_year)


def find_duplicates(households: list[Household]) -> list[list[str]]:
    """Groups of active household IDs that look like the same family, each sorted by ID."""
    active = sorted((h for h in households if h.status == "active"), key=lambda h: h.id)
    groups: list[list[Household]] = []
    for h in active:
        for group in groups:
            if same_family(group[0], h):
                group.append(h)
                break
        else:
            groups.append([h])
    return [[h.id for h in g] for g in groups if len(g) > 1]
