"""Generates Lifeline's seed data (data/ folder) for a given seed. Harness-side: agents never see this.

    python -m env.seed_data env/lifeline/data --seed 0

The data is random but always contains the cases that make each fact matter:
infants (F1), odd ration sizes (F2), lots where FIFO and FEFO disagree (F3),
households scoring just under each threshold (F7), van-only and closed roads (F8),
duplicate registrations spelled differently (F9), failed SMS (F10), and cycle-1
payments with keys and audit entries (F11, F12).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

LIFELINE = Path(__file__).resolve().parent / "lifeline"
if str(LIFELINE) not in sys.path:
    sys.path.insert(0, str(LIFELINE))

from core.ids import household_check_digit, make_household_id  # noqa: E402
from core.models import Household  # noqa: E402
from eligibility.rules import has_pregnant_member, is_eligible  # noqa: E402
from eligibility.scoring import vulnerability_score  # noqa: E402
from registry.dedup import find_duplicates, name_key  # noqa: E402

TODAY = date(2026, 3, 10)
CYCLE1_DAY = date(2026, 2, 25)
CASH = {"NVL": 40, "CPL": 45, "HGL": 50}
WAREHOUSES = {"WH-NVL-03": ("NVL", "North Valley depot"),
              "WH-CPL-05": ("CPL", "Port depot"),
              "WH-HGL-07": ("HGL", "Highlands depot")}
SITES = {"NVL": ["SITE-NVL-A", "SITE-NVL-B"], "CPL": ["SITE-CPL-A", "SITE-CPL-B"],
         "HGL": ["SITE-HGL-A", "SITE-HGL-B"]}

# Road statuses are fixed so every seed has the same logistics puzzle:
# NVL-B: short route is van-only (R), CPL-B: one route closed, the other van-only,
# HGL-A: R-12 closed so the northern route is used, HGL-B: only a van-only road.
ROADS = {"R-01": "A", "R-02": "A", "R-03": "R", "R-04": "A", "R-05": "A", "R-06": "A",
         "R-07": "A", "R-08": "X", "R-09": "R", "R-10": "A", "R-11": "A", "R-12": "X", "R-13": "R"}
ROUTES = [("RT-01", "WH-NVL-03", "SITE-NVL-A", ["R-01", "R-02"], 14),
          ("RT-02", "WH-NVL-03", "SITE-NVL-B", ["R-01", "R-03"], 22),
          ("RT-03", "WH-NVL-03", "SITE-NVL-B", ["R-04", "R-05"], 31),
          ("RT-04", "WH-CPL-05", "SITE-CPL-A", ["R-06"], 9),
          ("RT-05", "WH-CPL-05", "SITE-CPL-B", ["R-07", "R-08"], 18),
          ("RT-06", "WH-CPL-05", "SITE-CPL-B", ["R-07", "R-09"], 26),
          ("RT-07", "WH-HGL-07", "SITE-HGL-A", ["R-10", "R-12"], 20),
          ("RT-08", "WH-HGL-07", "SITE-HGL-A", ["R-10", "R-11"], 27),
          ("RT-09", "WH-HGL-07", "SITE-HGL-B", ["R-13"], 35)]

GIVEN = ["Amara", "Bilal", "Chiara", "Dawit", "Elif", "Farid", "Galina", "Hamza", "Ines", "Jomo",
         "Kenji", "Leyla", "Matteo", "Nadia", "Oskar", "Priya", "Rafael", "Sefa", "Tamar", "Umar",
         "Vesna", "Wanjiru", "Xavi", "Zainab", "Bruno", "Dilnoza", "Femi", "Halima", "Ivo", "Lucia"]
FAMILY = ["Okafor", "Haddad", "Lindqvist", "Bekele", "Moreau", "Tanaka", "Kowal", "Rahimi",
          "Silva", "Novak", "Oduya", "Ferreira", "Basu", "Quispe", "Dragan", "Abebe", "Lund",
          "Castell", "Mbeki", "Ortiz", "Varga", "Nakamura", "Duarte", "Sato"]
# Same family registered twice: second spelling sounds the same (equal Soundex codes).
VARIANTS = [("Kareem Odhiambo", "Karim Odiambo"), ("Yusuf Mensah", "Yousef Mensa"),
            ("Aisha Petrov", "Ayesha Petroff"), ("Teodor Achterberg", "Theodore Achterburg"),
            ("Mohamed Kahle", "Muhammad Kale")]
EXACT_DUP = "Selin Ward"
DECOY = ("Marta Quill", "Martha Quil")      # sounds the same, but a different birth year


def _birth(rng: random.Random, age_lo: float, age_hi: float) -> str:
    days = rng.randint(int(age_lo * 365.25) + 1, int(age_hi * 365.25) - 1)
    return (TODAY - timedelta(days=days)).isoformat()


def _members(rng: random.Random, head: str, head_birth: str | None = None) -> list[dict]:
    family = head.split()[-1]
    members = [{"name": head, "birth_date": head_birth or _birth(rng, 20, 70), "pregnant": False}]
    if rng.random() < 0.6:
        members.append({"name": f"{rng.choice(GIVEN)} {family}", "birth_date": _birth(rng, 19, 60),
                        "pregnant": False})
    for lo, hi, p in ((0, 2, 0.4), (2, 5, 0.5), (5, 17, 0.6), (66, 88, 0.3)):
        for _ in range(rng.choice([1, 1, 2]) if rng.random() < p else 0):
            members.append({"name": f"{rng.choice(GIVEN)} {family}", "birth_date": _birth(rng, lo, hi),
                            "pregnant": False})
    if rng.random() < 0.3:
        adults = [m for m in members if 18 <= _age(m) <= 45]
        if adults:
            rng.choice(adults)["pregnant"] = True
    return members


def _age(m: dict) -> int:
    b = date.fromisoformat(m["birth_date"])
    return TODAY.year - b.year - ((TODAY.month, TODAY.day) < (b.month, b.day))


def _household(rng, hid, region, head, *, head_birth=None, registered=None, members=None) -> dict:
    return {"id": hid, "region": region, "site": rng.choice(SITES[region]),
            "phone": f"+999 7{rng.randint(0, 9999999):07d}",
            "members": members or _members(rng, head, head_birth),
            "registered": (registered or (TODAY - timedelta(days=rng.randint(10, 60)))).isoformat(),
            "status": "active", "sms_ok": rng.random() > 0.08,
            "shelter_damaged": rng.random() < 0.6, "income_lost": rng.random() < 0.65,
            "disability": rng.random() < 0.3, "merged_into": None}


def _ids(rng: random.Random, n: int) -> list[str]:
    out, number = [], 1000
    while len(out) < n:
        number += rng.randint(1, 23)
        if number == 1042:          # reserved for the design.md example household
            continue
        if household_check_digit(f"{number:04d}") is not None:
            out.append(make_household_id(number))
    return out


def _registry(rng: random.Random) -> list[dict]:
    regions = ["NVL", "CPL", "HGL"]
    ids = iter(_ids(rng, 60))
    used_names = {n for pair in VARIANTS for n in pair} | {EXACT_DUP, *DECOY}
    keys = {name_key(n) for n in used_names}
    households = []

    # design.md example: 4 adults + 2 infants -> ration size 5 -> 2 kits.
    ex_members = [{"name": "Amara Okoro", "birth_date": "1984-05-11", "pregnant": False},
                  {"name": "Jomo Okoro", "birth_date": "1982-09-30", "pregnant": False},
                  {"name": "Ines Okoro", "birth_date": "2005-01-19", "pregnant": False},
                  {"name": "Femi Okoro", "birth_date": "1958-07-02", "pregnant": False},
                  {"name": "Sefa Okoro", "birth_date": "2025-06-14", "pregnant": False},
                  {"name": "Nadia Okoro", "birth_date": "2024-11-03", "pregnant": False}]
    ex = _household(rng, "HH-10427", "NVL", "Amara Okoro", members=ex_members)
    ex |= {"shelter_damaged": True, "income_lost": True, "disability": False, "site": "SITE-NVL-A"}
    households.append(ex)
    keys.add(name_key("Amara Okoro"))

    while len(households) < 44:
        name = f"{rng.choice(GIVEN)} {rng.choice(FAMILY)}"
        if name_key(name) in keys:
            continue
        keys.add(name_key(name))
        households.append(_household(rng, next(ids), rng.choice(regions), name))

    for first, second in VARIANTS + [(EXACT_DUP, EXACT_DUP)]:
        region = rng.choice(regions)
        a = _household(rng, next(ids), region, first, registered=TODAY - timedelta(days=rng.randint(30, 60)))
        b_members = [dict(m) for m in a["members"][: max(1, len(a["members"]) - rng.randint(0, 1))]]
        b_members[0]["name"] = second
        b_members[0]["birth_date"] = f"{a['members'][0]['birth_date'][:4]}-{rng.randint(1, 12):02d}-01"
        b = _household(rng, next(ids), region, second, members=b_members,
                       registered=TODAY - timedelta(days=rng.randint(3, 25)))
        households += [a, b]
    d1 = _household(rng, next(ids), "CPL", DECOY[0], head_birth="1979-03-03")
    d2 = _household(rng, next(ids), "CPL", DECOY[1], head_birth="1986-08-21")
    households += [d1, d2]

    for h in rng.sample(households[1:44], 3):
        h["status"] = "inactive"
    return sorted(households, key=lambda h: h["id"])


def _checks(households: list[dict]) -> list[str]:
    """Edge cases each fact needs. Returns the ones that are missing."""
    hs = [Household.from_dict(h) for h in households]
    active = [h for h in hs if h.status == "active"]
    score = {h.id: vulnerability_score(h, TODAY) for h in hs}
    preg = [h for h in active if has_pregnant_member(h)]
    nonpreg = [h for h in active if not has_pregnant_member(h)]
    infants = [h for h in active if any(m.age_on(TODAY) < 2 for m in h.members)]
    need = {
        "pregnant scoring 45-59 (F7)": sum(45 <= score[h.id] < 60 for h in preg) >= 3,
        "non-pregnant scoring 50-59 (F7 wrong cutoff)": sum(50 <= score[h.id] < 60 for h in nonpreg) >= 4,
        "non-pregnant scoring 55-59 (near-miss)": sum(55 <= score[h.id] < 60 for h in nonpreg) >= 2,
        "pregnant scoring 40-44 (near-miss)": sum(40 <= score[h.id] < 45 for h in preg) >= 1,
        "infants (F1)": len(infants) >= 6,
        "eligible 16-32": 16 <= sum(is_eligible(h, today=TODAY) for h in hs) <= 32,
        "every site has an eligible household": all(
            any(h.site == s and is_eligible(h, today=TODAY) for h in hs) for ss in SITES.values() for s in ss),
        "exactly 6 duplicate groups (F9)": len(find_duplicates(hs)) == 6,
    }
    return [k for k, ok in need.items() if not ok]


def _ledger(rng: random.Random) -> dict:
    lots, n = [], 0

    def lot(wh, sku, qty, received, expires):
        nonlocal n
        n += 1
        lots.append({"id": f"LOT-{n:04d}", "warehouse_id": wh, "sku": sku, "qty": qty,
                     "received": received, "expires": expires})

    for wh in WAREHOUSES:
        # Arrival order and expiry order disagree, so FIFO and FEFO pick different lots.
        lot(wh, "FOOD-KIT", rng.randint(30, 45), "2025-11-04", "2026-12-15")
        lot(wh, "FOOD-KIT", rng.randint(14, 22), "2026-01-20", f"2026-0{rng.randint(4, 6)}-1{rng.randint(0, 9)}")
        lot(wh, "FOOD-KIT", rng.randint(40, 60), "2026-02-18", "2027-02-01")
        lot(wh, "FOOD-KIT", rng.randint(4, 9), "2025-09-02", "2026-03-01")       # already expired
        lot(wh, "HYGIENE-KIT", rng.randint(20, 40), "2025-12-01", "2027-06-30")
        lot(wh, "HYGIENE-KIT", rng.randint(10, 20), "2026-02-02", "2026-09-30")
        lot(wh, "TARP", rng.randint(15, 30), "2025-10-10", "2030-01-01")

    reservations = []
    plan = [("WH-NVL-03", "FOOD-KIT", 6, "2026-03-05T09:00:00", 48, "held"),      # lapsed
            ("WH-NVL-03", "HYGIENE-KIT", 4, "2026-03-09T10:00:00", 72, "held"),   # still valid
            ("WH-CPL-05", "FOOD-KIT", 5, "2026-03-02T14:00:00", 24, "released"),
            ("WH-CPL-05", "FOOD-KIT", 8, "2026-03-07T08:00:00", 36, "held"),      # lapsed
            ("WH-HGL-07", "TARP", 3, "2026-03-08T16:00:00", 24, "held"),          # lapsed
            ("WH-HGL-07", "FOOD-KIT", 7, "2026-03-09T12:00:00", 48, "held"),      # still valid
            ("WH-HGL-07", "FOOD-KIT", 4, "2026-02-27T11:00:00", 48, "fulfilled")]
    for i, (wh, sku, qty, created, hold, status) in enumerate(plan, 1):
        when = datetime.fromisoformat(created)
        candidates = sorted((l for l in lots if l["warehouse_id"] == wh and l["sku"] == sku and l["qty"] > 0
                             and date.fromisoformat(l["expires"]) >= when.date()),
                            key=lambda l: (l["expires"], l["received"], l["id"]))
        taken, left = [], qty
        for l in candidates:
            take = min(l["qty"], left)
            taken.append({"lot_id": l["id"], "qty": take})
            left -= take
            if status != "released":
                l["qty"] -= take
            if not left:
                break
        reservations.append({"id": f"RSV-{i:04d}", "warehouse_id": wh, "sku": sku, "qty": qty,
                             "lots": taken, "created": created,
                             "expires_at": (when + timedelta(hours=hold)).isoformat(timespec="seconds"),
                             "status": status})
    return {"warehouses": {w: {"region": r, "name": name} for w, (r, name) in WAREHOUSES.items()},
            "lots": lots, "reservations": reservations}


def _outboxes(rng: random.Random, households: list[dict]):
    hs = [Household.from_dict(h) for h in households]
    paid = [h for h in hs if is_eligible(h, today=CYCLE1_DAY)
            and date.fromisoformat(h.registered) <= CYCLE1_DAY]
    payments, audit, sms = [], [], []
    for i, h in enumerate(paid, 1):
        at = f"{CYCLE1_DAY.isoformat()}T10:{i % 60:02d}:00"
        pid = f"PAY-{i:05d}"
        payments.append({"id": pid, "household_id": h.id, "amount": CASH[h.region],
                         "key": f"{h.id}:1", "sent_at": at})
        audit.append({"event": "payment", "actor": "scripts/cycle_payments.py", "ref": pid, "at": at})
    texts = {"SITE": "Lifeline: your aid is ready at {site} on {day}. Bring your household ID."}
    for h in (h for h in paid if h.sms_ok):
        params = {"site": h.site, "day": "Friday 27 Feb"}
        sms.append({"id": f"SMS-{len(sms) + 1:05d}", "household_id": h.id, "phone": h.phone,
                    "template_id": "DELIVERY_DAY", "params": params, "text": texts["SITE"].format(**params),
                    "queued_at": f"{CYCLE1_DAY.isoformat()}T12:00:00",
                    "delivery": "failed" if rng.random() < 0.25 else "delivered"})
    if not any(m["delivery"] == "failed" for m in sms):
        sms[0]["delivery"] = "failed"
    return payments, audit, sms


def generate(seed: int = 0) -> dict[str, object]:
    for attempt in range(500):
        rng = random.Random(seed * 1000 + attempt)
        households = _registry(rng)
        if not _checks(households):
            break
    else:
        raise RuntimeError(f"seed {seed}: no attempt satisfied {_checks(households)}")
    network = {"roads": {r: {"status": s} for r, s in ROADS.items()},
               "sites": {s: {"region": reg} for reg, ss in SITES.items() for s in ss},
               "routes": [{"id": i, "from": f, "to": t, "roads": rd, "km": km} for i, f, t, rd, km in ROUTES]}
    payments, audit, sms = _outboxes(rng, households)
    return {"registry.json": {"households": households}, "ledger.json": _ledger(rng),
            "network.json": network, "audit.jsonl": audit,
            "outbox/payments.jsonl": payments, "outbox/sms.jsonl": sms}


def write(dest: Path, seed: int = 0) -> None:
    for name, content in generate(seed).items():
        p = Path(dest) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".jsonl"):
            p.write_text("".join(json.dumps(r) + "\n" for r in content))
        else:
            p.write_text(json.dumps(content, indent=2) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dest")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    write(Path(args.dest), args.seed)
    print(f"wrote seed {args.seed} data to {args.dest}")
