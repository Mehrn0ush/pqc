"""'review-needed' issues. One issue per subject: while one is open, further changes are added as
comments instead of new issues, and a change that already has an issue (open or closed) is skipped."""

from __future__ import annotations

from dataclasses import dataclass

from pqc_tracker.config import ALGORITHMS, REVIEW_LABEL, STATUS_LABELS
from pqc_tracker.errors import CollectionError
from pqc_tracker.http import Fetcher

API = "https://api.github.com"


@dataclass(frozen=True)
class Action:
    kind: str  # "create" | "comment"
    title: str
    body: str
    issue_number: int | None = None


def marker(subject_type: str, subject_id: str) -> str:
    return f"<!-- pqc-subject: {subject_type}/{subject_id} -->"


def entry_marker(entry_id: str) -> str:
    return f"<!-- pqc-entry: {entry_id} -->"


def _impl_checklist(impl: dict | None) -> str:
    if not impl:
        return ""
    lines = ["", "Current recorded statuses (unchanged by automation):", ""]
    for alg, claim in impl["algorithms"].items():
        lines.append(f"- {ALGORITHMS[alg][0]}: {STATUS_LABELS[claim['status']]}")
    return "\n".join(lines)


def build_body(entry: dict, impl: dict | None) -> str:
    link = entry.get("url", "")
    return "\n".join(
        [
            marker(entry["subject_type"], entry["subject_id"]),
            entry_marker(entry["id"]),
            f"Automation detected: **{entry['title']}** ({entry['date']}).",
            "",
            f"Source: {link}" if link else "",
            "",
            "Automation does not change any status. A person needs to read the source and decide "
            "whether a status, version or note in `data/implementations.yaml` or `data/standards.yaml` "
            "should change. Any change needs an evidence URL (see CONTRIBUTING.md).",
            _impl_checklist(impl),
            "",
            "Close this issue when reviewed, whether or not anything changed.",
        ]
    ).strip()


def plan(entries: list[dict], existing: list[dict], impls_by_id: dict[str, dict]) -> list[Action]:
    """Pure planning step. `existing` is every issue (open and closed) carrying the review label."""
    actions: list[Action] = []
    known = {entry_marker_of(i) for i in existing} - {None}
    open_by_subject: dict[str, int] = {}
    for issue in existing:
        if issue.get("state") == "open":
            for line in (issue.get("body") or "").splitlines():
                if line.startswith("<!-- pqc-subject: "):
                    open_by_subject.setdefault(line, issue["number"])
    created_for: dict[str, int] = {}
    for e in entries:
        if e["kind"] == "status-change":
            continue  # human-confirmed changes need no review issue
        if entry_marker(e["id"]) in known:
            continue
        body = build_body(e, impls_by_id.get(e["subject_id"]))
        subject_line = marker(e["subject_type"], e["subject_id"])
        target = open_by_subject.get(subject_line)
        if target is not None:
            actions.append(Action("comment", e["title"], body, target))
        elif subject_line in created_for:
            actions.append(Action("comment", e["title"], body, None))
        else:
            actions.append(Action("create", f"{REVIEW_LABEL}: {e['title']}", body))
            created_for[subject_line] = -1
    return actions


def entry_marker_of(issue: dict) -> str | None:
    for line in (issue.get("body") or "").splitlines():
        if line.startswith("<!-- pqc-entry: "):
            return line
    return None


def list_review_issues(fetcher: Fetcher, repo: str) -> list[dict]:
    out: list[dict] = []
    for page in range(1, 11):
        batch = fetcher.get_json(
            f"{API}/repos/{repo}/issues?labels={REVIEW_LABEL}&state=all&per_page=100&page={page}"
        )
        if not isinstance(batch, list):
            raise CollectionError("issue listing: expected a list")
        out.extend(i for i in batch if "pull_request" not in i)
        if len(batch) < 100:
            return out
    raise CollectionError("issue listing: too many pages")


def ensure_label(fetcher: Fetcher, repo: str) -> None:
    try:
        fetcher.get_json(f"{API}/repos/{repo}/labels/{REVIEW_LABEL}")
    except CollectionError:
        fetcher.request_json(
            "POST",
            f"{API}/repos/{repo}/labels",
            {
                "name": REVIEW_LABEL,
                "color": "d889ae",
                "description": "Upstream change detected; a person must review",
            },
        )


def apply(fetcher: Fetcher, repo: str, entries: list[dict], impls: list[dict]) -> list[Action]:
    ensure_label(fetcher, repo)
    existing = list_review_issues(fetcher, repo)
    actions = plan(entries, existing, {i["id"]: i for i in impls})
    last_created: dict[str, int] = {}
    for a in actions:
        if a.kind == "create":
            made = fetcher.request_json(
                "POST",
                f"{API}/repos/{repo}/issues",
                {"title": a.title, "body": a.body, "labels": [REVIEW_LABEL]},
            )
            last_created[a.body.splitlines()[0]] = made["number"]
        else:
            number = a.issue_number or last_created.get(a.body.splitlines()[0])
            if number is None:
                raise CollectionError("cannot find issue to comment on")
            fetcher.request_json("POST", f"{API}/repos/{repo}/issues/{number}/comments", {"body": a.body})
    return actions
