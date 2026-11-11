"""Command line entry points used by the workflows and by humans.

validate            check all data files against their schemas
collect             fetch releases and drafts, write snapshot/changelog; fail closed
issues              open 'review-needed' issues for entries written by the last collect
fetch-baseline      download the previously published statuses and changelog (publish workflow)
build               validate, then render the static site
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pqc_tracker import changelog, issues, linkcheck, site, snapshot
from pqc_tracker.config import SITE_URL
from pqc_tracker.errors import CollectionError, TrackerError, ValidationError
from pqc_tracker.http import HttpFetcher
from pqc_tracker.util import atomic_write, dumps_json, iso_z, load_json, utcnow
from pqc_tracker.validate import ROOT, schema_errors, validate_data_dir


def _data_dir(args) -> Path:
    return Path(args.data_dir)


def cmd_validate(args) -> int:
    d = validate_data_dir(_data_dir(args))
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
    actions = issues.apply(HttpFetcher(), args.repo, entries, d["implementations"])
    for a in actions:
        print(f"{a.kind}: {a.title}")
    return 0


def cmd_fetch_baseline(args) -> int:
    """Download the live site's statuses and changelog. 404 on both means first deploy (no baseline).
    Anything else unexpected fails the run: publishing without history would drop changelog entries."""
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    found = 0
    for name in ("statuses.json", "changelog.json"):
        url = f"{args.site_url}/data/{name}"
        try:
            with urlopen(Request(url, headers={"User-Agent": "silastron-pqc-tracker"}), timeout=30) as resp:  # noqa: S310
                raw = resp.read(10 * 1024 * 1024).decode("utf-8")
            parsed = json.loads(raw)
        except HTTPError as exc:
            if exc.code == 404:
                print(f"no published {name} (404): treating as first deploy")
                continue
            raise CollectionError(f"baseline fetch failed for {url}: HTTP {exc.code}") from exc
        except (OSError, ValueError) as exc:
            raise CollectionError(f"baseline fetch failed for {url}: {exc}") from exc
        atomic_write(out / name, dumps_json(parsed))
        found += 1
    if found == 1:
        raise CollectionError("only one of statuses.json/changelog.json is published; refusing to build")
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
    data_dir = _data_dir(args)
    d = validate_data_dir(data_dir)
    now = utcnow()
    prev_dir = Path(args.previous_dir) if args.previous_dir else None
    baseline = prev_log = None
    if prev_dir and (prev_dir / "statuses.json").exists():
        baseline = load_json(prev_dir / "statuses.json")
        prev_log = load_json(prev_dir / "changelog.json")
        bad = schema_errors("changelog", prev_log, ROOT / "schemas")
        if (
            bad
            or not isinstance(baseline.get("implementations"), dict)
            or not isinstance(baseline.get("standards"), dict)
        ):
            raise ValidationError("previously published baseline is malformed: " + "; ".join(bad))
    new_entries = changelog.diff_statuses(
        baseline, d["implementations"], d["standards"], now.date().isoformat()
    )
    entries = changelog.merge_for_publication(
        d["changelog"]["entries"], (prev_log or {}).get("entries", []), new_entries
    )
    ctx = site.Context(d["implementations"], d["standards"], d["snapshot"], d["status"], entries, now)
    pages = site.build_site(ctx, Path(args.out), ROOT / "schemas")
    print(
        f"built {len(pages)} pages into {args.out}; {len(new_entries)} new status entries; "
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
    i.set_defaults(fn=cmd_issues)
    f = sub.add_parser("fetch-baseline")
    f.add_argument("--site-url", default=SITE_URL)
    f.add_argument("--out", default="dist-baseline")
    f.set_defaults(fn=cmd_fetch_baseline)
    sub.add_parser("check-links").set_defaults(fn=cmd_check_links)
    sub.add_parser("record-failure").set_defaults(fn=cmd_record_failure)
    b = sub.add_parser("build")
    b.add_argument("--out", default="dist/site")
    b.add_argument("--previous-dir", default=None)
    b.set_defaults(fn=cmd_build)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except TrackerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
