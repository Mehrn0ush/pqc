"""Command line entry points used by the workflows and by humans.

validate            check all data files against their schemas
collect             fetch releases and drafts, write snapshot/changelog; fail closed
issues              open 'review-needed' issues for entries written by the last collect
build               validate, then render the static site
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from pqc_tracker import changelog, history, issues, linkcheck, site, snapshot
from pqc_tracker.errors import TrackerError
from pqc_tracker.http import HttpFetcher
from pqc_tracker.util import atomic_write, dumps_json, iso_z, load_json, utcnow
from pqc_tracker.validate import ROOT, semantic_warnings, validate_data_dir


def _data_dir(args) -> Path:
    return Path(args.data_dir)


def cmd_validate(args) -> int:
    d = validate_data_dir(_data_dir(args))
    for w in semantic_warnings(d["implementations"], date.today()):
        print(f"warning: {w}")
    print(
        f"ok: {len(d['implementations'])} implementations, {len(d['standards'])} standards, "
        f"{len(d['changelog']['entries'])} changelog entries"
    )
    return 0


def cmd_collect(args) -> int:
    data_dir = _data_dir(args)
    d = validate_data_dir(data_dir)
    entries = snapshot.run_collect(HttpFetcher(), d["implementations"], d["standards"], data_dir)
    atomic_write(Path(args.entries_out), dumps_json(entries))
    print(f"collected; {len(entries)} new changelog entries")
    return 0


def cmd_issues(args) -> int:
    data_dir = _data_dir(args)
    d = validate_data_dir(data_dir)
    entries = load_json(Path(args.entries))
    if args.dry_run:
        actions = issues.preview(HttpFetcher(), args.repo, entries, d["implementations"])
    else:
        actions = issues.apply(HttpFetcher(), args.repo, entries, d["implementations"])
    for a in actions:
        print(f"{'would ' if args.dry_run else ''}{a.kind}: {a.title}")
    return 0


def cmd_record_failure(args) -> int:
    """Used by the Collect workflow after a failure that happened after collection itself
    (collection errors already record their own detail)."""
    data_dir = _data_dir(args)
    status_path = data_dir / "collection-status.json"
    snap_path = data_dir / "snapshots" / "latest.json"
    current = load_json(status_path) if status_path.exists() else None
    if current and current.get("status") == "failed":
        print("failure already recorded")
        return 0
    last_good = load_json(snap_path)["collected_at"] if snap_path.exists() else None
    status = {
        "schema_version": "1.0.0",
        "status": "failed",
        "last_good_collected_at": last_good,
        "failed_at": iso_z(utcnow()),
        "error": "Collect workflow failed after collection; see the workflow run log.",
    }
    atomic_write(status_path, dumps_json(status))
    return 0


def cmd_check_links(args) -> int:
    d = validate_data_dir(_data_dir(args))
    errors, warnings = linkcheck.check(d["implementations"], d["standards"])
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    print(f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def cmd_build(args) -> int:
    """Build the static site. The changelog is the committed machine log plus the status changes derived
    from the git history of the YAML files. Nothing is read from the live site."""
    data_dir = _data_dir(args)
    d = validate_data_dir(data_dir)
    now = utcnow()
    confirmed = history.published_status_changes(Path(args.repo))
    entries = changelog.merge_for_publication(d["changelog"]["entries"], confirmed)
    ctx = site.Context(d["implementations"], d["standards"], d["snapshot"], d["status"], entries, now)
    pages = site.build_site(ctx, Path(args.out), ROOT / "schemas")
    print(
        f"built {len(pages)} pages into {args.out}; {len(confirmed)} confirmed status changes from git history; "
        f"stale_since={ctx.stale_since}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pqc-tracker")
    p.add_argument("--data-dir", default=str(ROOT / "data"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    c = sub.add_parser("collect")
    c.add_argument("--entries-out", default="dist/new-entries.json")
    c.set_defaults(fn=cmd_collect)
    i = sub.add_parser("issues")
    i.add_argument("--entries", default="dist/new-entries.json")
    i.add_argument("--repo", required=True)
    i.add_argument(
        "--dry-run", action="store_true", help="list what would be opened or commented; change nothing"
    )
    i.set_defaults(fn=cmd_issues)
    sub.add_parser("check-links").set_defaults(fn=cmd_check_links)
    sub.add_parser("record-failure").set_defaults(fn=cmd_record_failure)
    b = sub.add_parser("build")
    b.add_argument("--out", default="dist/site")
    b.add_argument("--repo", default=str(ROOT), help="git repository whose history holds the status changes")
    b.set_defaults(fn=cmd_build)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except TrackerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
