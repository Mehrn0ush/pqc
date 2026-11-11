"""IETF Datatracker collector. Reads doc.json for each tracked draft."""

from __future__ import annotations

import re

from pqc_tracker.errors import CollectionError
from pqc_tracker.http import Fetcher

BASE = "https://datatracker.ietf.org"
_REV = re.compile(r"^(\d{2}|rfc\d+)$")
_RFC = re.compile(r"^rfc(\d+)$")
_STATE = {"active", "rfc", "expired", "replaced", "withdrawn"}


def collect_draft(fetcher: Fetcher, name: str) -> dict:
    where = f"datatracker {name}"
    doc = fetcher.get_json(f"{BASE}/doc/{name}/doc.json")
    if not isinstance(doc, dict) or doc.get("name") != name:
        raise CollectionError(f"{where}: unexpected document")
    rev, state_raw, time = doc.get("rev"), doc.get("state"), doc.get("time")
    if not isinstance(rev, str) or not _REV.match(rev):
        raise CollectionError(f"{where}: invalid rev {rev!r}")
    if not isinstance(state_raw, str) or state_raw.lower() not in _STATE:
        raise CollectionError(f"{where}: unrecognised state {state_raw!r}")
    if not isinstance(time, str) or len(time) < 10:
        raise CollectionError(f"{where}: invalid time")
    state = state_raw.lower()
    rfc = None
    if state == "rfc":
        history = doc.get("rev_history")
        last = history[-1].get("name") if isinstance(history, list) and history else None
        m = _RFC.match(last or "")
        if not m:
            raise CollectionError(f"{where}: state RFC but no RFC number in history")
        rfc = f"RFC {int(m.group(1))}"
    iesg = doc.get("iesg_state")
    if iesg is not None and not isinstance(iesg, str):
        raise CollectionError(f"{where}: invalid iesg_state")
    return {
        "rev": rev,
        "state": state,
        "iesg_state": iesg,
        "rfc": rfc,
        "updated_at": time[:10],
        "url": f"{BASE}/doc/{name}/",
    }
