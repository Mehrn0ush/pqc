"""Changelog logic.

Two kinds of entry, never mixed up:
- machine-detected facts (new release, new draft revision, draft state change), found by diffing
  consecutive snapshots. They say nothing about support status.
- human-confirmed status changes, found by diffing the YAML files against the statuses of the
  previously published build.
"""

from __future__ import annotations

from typing import Any

from pqc_tracker.config import ALGORITHMS, STANDARD_STATUS_LABELS, STATUS_LABELS
from pqc_tracker.util import short_hash

SCHEMA_VERSION = "1.0.0"


def _entry(
    *,
    date: str,
    kind: str,
    subject_type: str,
    subject_id: str,
    title: str,
    detected_by: str,
    algorithm: str | None = None,
    frm: str | None = None,
    to: str | None = None,
    url: str | None = None,
    id_parts: tuple[str | None, ...] = (),
) -> dict:
    e: dict[str, Any] = {
        "id": short_hash(kind, subject_type, subject_id, algorithm, *id_parts),
        "date": date,
        "kind": kind,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "title": title,
        "detected_by": detected_by,
    }
    if algorithm:
        e["algorithm"] = algorithm
    if frm is not None:
        e["from"] = frm
    if to is not None:
        e["to"] = to
    if url:
        e["url"] = url
    if detected_by == "human":
        e["human_confirmed"] = True
    return e


def _draft_label(d: dict) -> str:
    return d["rfc"] if d.get("rfc") else d["state"]


def diff_snapshots(
    previous: dict | None,
    new: dict,
    impl_names: dict[str, str],
    draft_ids: dict[str, str],
    detected_on: str,
) -> list[dict]:
    """Machine-detected changes between two snapshots. With no previous snapshot there is nothing
    to compare: the first snapshot is a baseline, not a burst of 'new' events."""
    if previous is None:
        return []
    out: list[dict] = []
    for pid, rel in sorted(new["releases"].items()):
        old = previous["releases"].get(pid)
        if old is None or old["tag"] == rel["tag"]:
            continue
        name = impl_names.get(pid, pid)
        out.append(
            _entry(
                date=rel["published_at"] or detected_on,
                kind="release",
                subject_type="implementation",
                subject_id=pid,
                title=f"{name}: new release {rel['tag']}",
                detected_by="machine",
                frm=old["tag"],
                to=rel["tag"],
                url=rel["url"],
                id_parts=(rel["tag"],),
            )
        )
    for dname, d in sorted(new["drafts"].items()):
        old = previous["drafts"].get(dname)
        if old is None:
            continue
        sid = draft_ids.get(dname, dname)
        if old["rev"] != d["rev"] and d["state"] != "rfc":
            out.append(
                _entry(
                    date=d["updated_at"],
                    kind="draft-revision",
                    subject_type="standard",
                    subject_id=sid,
                    title=f"{dname}: revision -{d['rev']} posted",
                    detected_by="machine",
                    frm=old["rev"],
                    to=d["rev"],
                    url=d["url"],
                    id_parts=(d["rev"],),
                )
            )
        if (old["state"], old.get("iesg_state")) != (d["state"], d.get("iesg_state")):
            was = _draft_label(old) if old["state"] != "active" else (old.get("iesg_state") or "active")
            now_ = _draft_label(d) if d["state"] != "active" else (d.get("iesg_state") or "active")
            out.append(
                _entry(
                    date=d["updated_at"],
                    kind="draft-state",
                    subject_type="standard",
                    subject_id=sid,
                    title=f"{dname}: Datatracker state {was} to {now_}",
                    detected_by="machine",
                    frm=was,
                    to=now_,
                    url=d["url"],
                    id_parts=(now_, detected_on),
                )
            )
    return out


def append_entries(log: dict, entries: list[dict]) -> dict:
    """Append-only: existing entries are never modified or removed; duplicate ids are skipped."""
    seen = {e["id"] for e in log["entries"]}
    added = [e for e in entries if e["id"] not in seen]
    return {"schema_version": SCHEMA_VERSION, "entries": [*log["entries"], *added]}


def statuses_of(implementations: list[dict], standards: list[dict]) -> dict:
    """The compact status map stored with each published build and used as the next build's baseline."""
    return {
        "schema_version": SCHEMA_VERSION,
        "implementations": {
            i["id"]: {a: c["status"] for a, c in i["algorithms"].items()} for i in implementations
        },
        "standards": {s["id"]: s["status"] for s in standards},
    }


def diff_statuses(
    baseline: dict | None,
    implementations: list[dict],
    standards: list[dict],
    built_on: str,
) -> list[dict]:
    """Human-confirmed status changes: YAML now versus the previously published build.
    No baseline (first deploy) means no entries."""
    if baseline is None:
        return []
    out: list[dict] = []
    base_impl = baseline.get("implementations", {})
    for impl in implementations:
        old = base_impl.get(impl["id"])
        if old is None:
            out.append(
                _entry(
                    date=built_on,
                    kind="status-change",
                    subject_type="implementation",
                    subject_id=impl["id"],
                    title=f"{impl['name']} added to the tracker",
                    detected_by="human",
                    to="added",
                    id_parts=("added", built_on),
                )
            )
            continue
        for alg, claim in impl["algorithms"].items():
            if old.get(alg) != claim["status"]:
                label = ALGORITHMS[alg][0]
                was = STATUS_LABELS.get(old.get(alg, ""), "not tracked")
                out.append(
                    _entry(
                        date=built_on,
                        kind="status-change",
                        subject_type="implementation",
                        subject_id=impl["id"],
                        algorithm=alg,
                        title=f"{impl['name']}, {label}: {was} to {STATUS_LABELS[claim['status']]}",
                        detected_by="human",
                        frm=old.get(alg),
                        to=claim["status"],
                        url=claim.get("evidence_url"),
                        id_parts=(claim["status"], built_on),
                    )
                )
    base_std = baseline.get("standards", {})
    for std in standards:
        old = base_std.get(std["id"])
        if old is None:
            out.append(
                _entry(
                    date=built_on,
                    kind="status-change",
                    subject_type="standard",
                    subject_id=std["id"],
                    title=f"{std['title']} added to the tracker",
                    detected_by="human",
                    to="added",
                    id_parts=("added", built_on),
                )
            )
        elif old != std["status"]:
            out.append(
                _entry(
                    date=built_on,
                    kind="status-change",
                    subject_type="standard",
                    subject_id=std["id"],
                    title=(
                        f"{std['title']}: {STANDARD_STATUS_LABELS.get(old, old)} to "
                        f"{STANDARD_STATUS_LABELS[std['status']]}"
                    ),
                    detected_by="human",
                    frm=old,
                    to=std["status"],
                    url=std["source_url"],
                    id_parts=(std["status"], built_on),
                )
            )
    return out


def merge_for_publication(*groups: list[dict]) -> list[dict]:
    """Union of the repo log, the previously published log and newly diffed entries, de-duplicated by
    id (first occurrence wins) and sorted newest first. Nothing already published can disappear."""
    seen: dict[str, dict] = {}
    for group in groups:
        for e in group:
            seen.setdefault(e["id"], e)
    return sorted(seen.values(), key=lambda e: (e["date"], e["id"]), reverse=True)
