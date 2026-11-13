"""Watchdog: is the live site still being updated?

Runs outside Collect and Publish (watchdog.yml), so it still works when either of them is broken. It looks
at the live /build.json and at main's latest data commit, decides whether the site is stale, and keeps one
GitHub issue labelled `site-stale` in step with that decision. The decision functions are pure: every time
and every response is passed in."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from pqc_tracker import smoke
from pqc_tracker.errors import CollectionError
from pqc_tracker.http import Fetcher
from pqc_tracker.util import iso_z, parse_iso_z

LABEL = "site-stale"
STALE_BUILD = timedelta(hours=48)
BEHIND_MAIN = timedelta(hours=6)
COMMENT_EVERY = timedelta(hours=24)
FETCH_ATTEMPTS = 3
API = "https://api.github.com"
ISSUE_MARKER = "<!-- pqc-watchdog: site-stale -->"
COMMENT_MARKER = "<!-- pqc-watchdog: comment -->"
OPS_DOC = "https://github.com/Mehrn0ush/pqc/blob/main/docs/operations.md"


@dataclass(frozen=True)
class Alert:
    code: str  # build-old | behind-main | fetch-failed | run-failed
    message: str


@dataclass(frozen=True)
class Live:
    build: dict | None
    error: str | None  # set when the live site could not be read FETCH_ATTEMPTS times in a row


@dataclass(frozen=True)
class DataCommit:
    sha: str
    committed_at: datetime
    live_has_it: bool | None  # None: GitHub could not say


@dataclass(frozen=True)
class Plan:
    action: str  # create | comment | close | none
    title: str = ""
    body: str = ""
    issue_number: int | None = None


def fetch_live(
    base_url: str,
    fetch: Callable[[str], dict] = smoke.fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = FETCH_ATTEMPTS,
    interval: float = 30,
) -> Live:
    """Read the live /build.json and /data/latest.json, three tries with a cache-busting query."""
    error = ""
    for attempt in range(1, attempts + 1):
        stamp = time.time_ns()
        try:
            build = fetch(f"{base_url}/build.json?cb={stamp}")
            fetch(f"{base_url}/data/latest.json?cb={stamp}")
            if not isinstance(build, dict) or "commit" not in build or "built_at" not in build:
                raise ValueError("build.json is not in the expected shape")
            return Live(build, None)
        except (OSError, ValueError, KeyError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        if attempt < attempts:
            sleep(interval)
    return Live(None, f"{attempts} fetches in a row failed; last error: {error}")


def evaluate(
    now: datetime,
    live: Live,
    data_commit: DataCommit | None,
    failed_run: dict | None = None,
) -> list[Alert]:
    """Every reason the site counts as stale right now. Empty means healthy."""
    alerts: list[Alert] = []
    if failed_run:
        alerts.append(
            Alert(
                "run-failed",
                f"The {failed_run['name']} workflow finished with {failed_run['conclusion']}: {failed_run['url']}",
            )
        )
    if live.error:
        alerts.append(Alert("fetch-failed", f"The live site could not be read: {live.error}"))
        return alerts
    built_at = parse_iso_z(live.build["built_at"])
    age = now - built_at
    if age > STALE_BUILD:
        alerts.append(
            Alert(
                "build-old",
                f"The live build is {age.total_seconds() / 3600:.0f} hours old (built {live.build['built_at']}, "
                f"commit {live.build['commit'][:7]}); the limit is {STALE_BUILD.total_seconds() / 3600:.0f}.",
            )
        )
    if data_commit and data_commit.live_has_it is False and now - data_commit.committed_at > BEHIND_MAIN:
        behind = (now - data_commit.committed_at).total_seconds() / 3600
        alerts.append(
            Alert(
                "behind-main",
                f"main's latest data commit {data_commit.sha[:7]} ({iso_z(data_commit.committed_at)}) is not in "
                f"the live site (live commit {live.build['commit'][:7]}) after {behind:.0f} hours; "
                f"the limit is {BEHIND_MAIN.total_seconds() / 3600:.0f}.",
            )
        )
    return alerts


def _alert_lines(alerts: list[Alert]) -> str:
    return "\n".join(f"- **{a.code}**: {a.message}" for a in alerts)


def plan_issue(
    now: datetime,
    alerts: list[Alert],
    open_issue: dict | None,
    comments: list[dict],
    allow_close: bool,
    owner: str,
) -> Plan:
    """One open `site-stale` issue at most. Comment on it at most once per day; close it, with a comment,
    when the check passes again (`allow_close` is false for the failed-run trigger, which only raises)."""
    if alerts:
        if open_issue is None:
            body = "\n".join(
                [
                    ISSUE_MARKER,
                    f"The watchdog found the site stale at {iso_z(now)}:",
                    "",
                    _alert_lines(alerts),
                    "",
                    f"What each alert means and how to recover: {OPS_DOC}",
                    "",
                    "This issue closes itself, with a comment, when a later check passes. Further alerts "
                    "are added as comments, at most once a day.",
                ]
            )
            return Plan("create", "Site stale: pqc.silastron.com is not being updated", body)
        last = parse_iso_z(open_issue["created_at"])
        for c in comments:
            if COMMENT_MARKER in (c.get("body") or ""):
                last = max(last, parse_iso_z(c["created_at"]))
        if now - last >= COMMENT_EVERY:
            body = "\n".join(
                [COMMENT_MARKER, f"Still stale at {iso_z(now)}:", "", _alert_lines(alerts), "", OPS_DOC]
            )
            return Plan("comment", body=body, issue_number=open_issue["number"])
        return Plan("none")
    if open_issue is not None and allow_close:
        body = f"{COMMENT_MARKER}\nRecovered: the check passed at {iso_z(now)}. Closing."
        return Plan("close", body=body, issue_number=open_issue["number"])
    return Plan("none")


# ---------------------------------------------------------------- GitHub


def latest_data_commit(fetcher: Fetcher, repo: str, live_commit: str) -> DataCommit | None:
    """main's latest commit that touched data/, and whether the live build contains it."""
    rows = fetcher.get_json(f"{API}/repos/{repo}/commits?sha=main&path=data&per_page=1")
    if not rows:
        return None
    sha = rows[0]["sha"]
    when = parse_iso_z(rows[0]["commit"]["committer"]["date"])
    try:
        cmp = fetcher.get_json(f"{API}/repos/{repo}/compare/{sha}...{live_commit}")
        has = cmp["status"] in ("ahead", "identical")
    except (CollectionError, KeyError):
        has = None
    return DataCommit(sha, when, has)


def open_site_stale_issue(fetcher: Fetcher, repo: str) -> tuple[dict | None, list[dict]]:
    issues = fetcher.get_json(f"{API}/repos/{repo}/issues?labels={LABEL}&state=open&per_page=30")
    issues = [i for i in issues if "pull_request" not in i]
    if not issues:
        return None, []
    oldest = sorted(issues, key=lambda i: i["number"])[0]
    comments = fetcher.get_json(f"{API}/repos/{repo}/issues/{oldest['number']}/comments?per_page=100")
    return oldest, comments


def ensure_label(fetcher: Fetcher, repo: str) -> None:
    try:
        fetcher.get_json(f"{API}/repos/{repo}/labels/{LABEL}")
    except CollectionError:
        fetcher.request_json(
            "POST",
            f"{API}/repos/{repo}/labels",
            {"name": LABEL, "color": "b60205", "description": "The live site is not being updated"},
        )


def apply(fetcher: Fetcher, repo: str, plan: Plan, owner: str) -> None:
    if plan.action == "create":
        ensure_label(fetcher, repo)
        fetcher.request_json(
            "POST",
            f"{API}/repos/{repo}/issues",
            {"title": plan.title, "body": plan.body, "labels": [LABEL], "assignees": [owner]},
        )
    elif plan.action in ("comment", "close"):
        fetcher.request_json(
            "POST", f"{API}/repos/{repo}/issues/{plan.issue_number}/comments", {"body": plan.body}
        )
        if plan.action == "close":
            fetcher.request_json(
                "PATCH", f"{API}/repos/{repo}/issues/{plan.issue_number}", {"state": "closed"}
            )


def run(
    repo: str,
    base_url: str,
    owner: str,
    now: datetime,
    fetcher: Fetcher,
    failed_run: dict | None = None,
    dry_run: bool = False,
    fetch: Callable[[str], dict] = smoke.fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> tuple[list[Alert], Plan]:
    live = fetch_live(base_url, fetch=fetch, sleep=sleep)
    data_commit = None
    if live.build:
        try:
            data_commit = latest_data_commit(fetcher, repo, live.build["commit"])
        except CollectionError as exc:
            log(f"could not read main's data commit ({exc}); skipping the behind-main check")
    alerts = evaluate(now, live, data_commit, failed_run)
    issue, comments = open_site_stale_issue(fetcher, repo)
    plan = plan_issue(now, alerts, issue, comments, allow_close=failed_run is None, owner=owner)
    for a in alerts:
        log(f"alert {a.code}: {a.message}")
    log(
        f"{len(alerts)} alert(s); issue action: {plan.action}"
        + (" (dry run, nothing changed)" if dry_run else "")
    )
    if not dry_run:
        apply(fetcher, repo, plan, owner)
    return alerts, plan
