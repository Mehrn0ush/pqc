"""Collect everything into one new snapshot. All-or-nothing: any failure raises and nothing is written."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pqc_tracker import changelog, expiry, ietf, sources
from pqc_tracker.errors import CollectionError, TrackerError
from pqc_tracker.http import Fetcher
from pqc_tracker.util import atomic_write, dumps_json, iso_z, load_json, utcnow

SCHEMA_VERSION = "1.0.0"


def collect_all(fetcher: Fetcher, implementations: list[dict], standards: list[dict], now: datetime) -> dict:
    releases: dict[str, dict] = {}
    drafts: dict[str, dict] = {}
    errors: list[str] = []
    for impl in implementations:
        try:
            releases[impl["id"]] = sources.collect_release(fetcher, impl)
        except TrackerError as exc:
            errors.append(f"{impl['id']}: {exc}")
    for std in standards:
        name = std.get("datatracker_name")
        if not name:
            continue
        try:
            drafts[name] = ietf.collect_draft(fetcher, name)
        except TrackerError as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        # One bad source poisons the run: never publish a partially updated snapshot.
        raise CollectionError("; ".join(errors))
    return {
        "schema_version": SCHEMA_VERSION,
        "collected_at": iso_z(now),
        "releases": releases,
        "drafts": drafts,
    }


def run_collect(
    fetcher: Fetcher,
    implementations: list[dict],
    standards: list[dict],
    data_dir: Path,
    now: datetime | None = None,
) -> list[dict]:
    """Collect, diff against the previous snapshot, and write snapshot + changelog + status.

    Returns the new changelog entries. On failure writes only collection-status.json, then re-raises."""
    now = now or utcnow()
    snap_path = data_dir / "snapshots" / "latest.json"
    log_path = data_dir / "changelog.json"
    status_path = data_dir / "collection-status.json"
    previous = load_json(snap_path) if snap_path.exists() else None
    last_good = previous["collected_at"] if previous else None
    try:
        new = collect_all(fetcher, implementations, standards, now)
        names = {i["id"]: i["name"] for i in implementations}
        titles = {s["datatracker_name"]: s["id"] for s in standards if s.get("datatracker_name")}
        entries = changelog.diff_snapshots(previous, new, names, titles, detected_on=now.date().isoformat())
        log = load_json(log_path) if log_path.exists() else {"schema_version": SCHEMA_VERSION, "entries": []}
        seen = {e["id"] for e in log["entries"]}
        entries += [e for e in expiry.expiry_entries(implementations, now.date()) if e["id"] not in seen]
        merged = changelog.append_entries(log, entries)
    except TrackerError as exc:
        atomic_write(
            status_path,
            dumps_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "failed",
                    "last_good_collected_at": last_good,
                    "failed_at": iso_z(now),
                    "error": str(exc)[:500],
                }
            ),
        )
        raise
    atomic_write(snap_path, dumps_json(new))
    atomic_write(log_path, dumps_json(merged))
    atomic_write(
        status_path,
        dumps_json(
            {"schema_version": SCHEMA_VERSION, "status": "ok", "last_good_collected_at": new["collected_at"]}
        ),
    )
    return entries
