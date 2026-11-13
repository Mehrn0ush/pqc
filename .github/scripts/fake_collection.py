"""CI only: pretend Collect ran at the given time by rewriting the collection dates in the work tree.

    python .github/scripts/fake_collection.py 2027-12-17T08:00:00Z

Used by the clock matrix in ci.yml to prove that no test depends on the snapshot's collected_at. It edits
files in the CI checkout only and is never run by a workflow that commits."""

from __future__ import annotations

import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"


def main(when: str) -> int:
    for rel, key in (
        ("snapshots/latest.json", "collected_at"),
        ("collection-status.json", "last_good_collected_at"),
    ):
        path = DATA / rel
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc[key] = when
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"collection dates set to {when}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
