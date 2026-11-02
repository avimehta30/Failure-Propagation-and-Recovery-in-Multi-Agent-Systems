"""Reading and writing the shared data files in data/.

    registry.json, ledger.json   mutable: read, change, write back whole
    network.json                 roads, routes and sites (reference data)
    audit.jsonl                  append-only
    outbox/sms.jsonl             append-only: a line here counts as SENT
    outbox/payments.jsonl        append-only: a line here counts as SENT

There is deliberately no function to edit or delete a line in an append-only file.
"""

import json
import os
from pathlib import Path

from config.settings import data_dir


def path(name: str) -> Path:
    return data_dir() / name


def read_json(name: str):
    with open(path(name)) as f:
        return json.load(f)


def write_json(name: str, obj) -> None:
    target = path(name)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.replace(tmp, target)


def read_jsonl(name: str) -> list[dict]:
    p = path(name)
    if not p.exists():
        return []
    with open(p) as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(name: str, record: dict) -> None:
    p = path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(record) + "\n")
