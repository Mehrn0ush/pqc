"""Expiry of 'planned' statements.

A 'planned' cell rests on a maintainer statement. It stops counting 365 days after the statement, or the
day after the target the statement named, whichever is first. Expiry never rewrites the YAML and never
fails a build: the site shows the cell as 'No statement found' with the old statement linked, Collect
records one machine changelog entry dated on the expiry day, and review-needed issues ask a person to
re-confirm the statement or change the cell."""

from __future__ import annotations

import copy
from datetime import date, timedelta

from pqc_tracker import changelog
from pqc_tracker.config import ALGORITHMS

MAX_AGE_DAYS = 365
WARN_DAYS = 30


def expires_on(c: dict) -> date | None:
    """First day on which a 'planned' cell no longer counts; None for any other status."""
    if c["status"] != "planned":
        return None
    day = date.fromisoformat(c["statement_date"]) + timedelta(days=MAX_AGE_DAYS + 1)
    if "statement_target_date" in c:
        day = min(day, date.fromisoformat(c["statement_target_date"]) + timedelta(days=1))
    return day


def is_expired(c: dict, today: date) -> bool:
    day = expires_on(c)
    return day is not None and today >= day


def days_left(c: dict, today: date) -> int | None:
    day = expires_on(c)
    return None if day is None else (day - today).days


def planned_cells(impls: list[dict]):
    for i in impls:
        for alg, c in i["algorithms"].items():
            if c["status"] == "planned":
                yield i, alg, c


def effective(impls: list[dict], today: date) -> list[dict]:
    """The implementations as the site shows them: expired 'planned' cells become 'no-statement-found'."""
    out = copy.deepcopy(impls)
    for i in out:
        for alg, c in list(i["algorithms"].items()):
            if not is_expired(c, today):
                continue
            i["algorithms"][alg] = {
                "status": "no-statement-found",
                "verified_on": c["verified_on"],
                "note": c.get("note", ""),
                "expired_planned": {
                    "expired_on": expires_on(c).isoformat(),
                    "statement_date": c["statement_date"],
                    "url": c["evidence_url"],
                },
            }
    return out


def expiry_entries(impls: list[dict], today: date) -> list[dict]:
    """One machine entry per expired cell, dated on the day it expired. Ids are deterministic."""
    out = []
    for i, alg, c in planned_cells(impls):
        if not is_expired(c, today):
            continue
        day = expires_on(c).isoformat()
        out.append(
            changelog.entry(
                date=day,
                kind="planned-expired",
                subject_type="implementation",
                subject_id=i["id"],
                algorithm=alg,
                title=(
                    f"{i['name']}, {ALGORITHMS[alg][0]}: 'planned' statement of {c['statement_date']} "
                    "expired; shown as No statement found"
                ),
                detected_by="machine",
                frm="planned",
                to="no-statement-found",
                url=c["evidence_url"],
                id_parts=(c["statement_date"], day),
            )
        )
    return out
