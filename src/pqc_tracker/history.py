"""Confirmed status changes, derived from the git history of the two human-edited YAML files.

Deterministic and rebuildable from a fresh clone: no network, no published site. Each commit on the
first-parent line of main that changes data/implementations.yaml or data/standards.yaml is compared
with the previous such commit; every changed status becomes one 'status-change' entry dated by that
commit. The first commit that has both files is the baseline and produces no entries."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from pqc_tracker import changelog
from pqc_tracker.config import REPO_URL
from pqc_tracker.errors import ValidationError

BASELINE_FILE = "data/changelog_baseline.txt"
FILES = ("data/implementations.yaml", "data/standards.yaml")
# Status names that were renamed in the data model. History is normalised so a rename is not a change.
LEGACY_STATUS = {"unverified": "not-checked"}


def _git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        raise ValidationError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _show(repo: Path, sha: str, path: str) -> list[dict] | None:
    proc = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "show", f"{sha}:{path}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        return None  # file does not exist in that commit
    try:
        data = yaml.safe_load(proc.stdout)
    except yaml.YAMLError as exc:
        raise ValidationError(f"{path} at {sha[:12]} is not valid YAML: {exc}") from exc
    if not isinstance(data, list):
        raise ValidationError(f"{path} at {sha[:12]} is not a list")
    return data


def _normalise(impls: list[dict], stds: list[dict]) -> None:
    for i in impls:
        for c in i["algorithms"].values():
            c["status"] = LEGACY_STATUS.get(c["status"], c["status"])
    for s in stds:
        s["status"] = LEGACY_STATUS.get(s["status"], s["status"])


def read_baseline(repo: Path) -> str | None:
    """The commit named in data/changelog_baseline.txt: the first non-blank line that is not a comment.
    None when the file is missing or names no commit, which means tracking has not begun."""
    path = repo / BASELINE_FILE
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            if not re.fullmatch(r"[0-9a-f]{7,40}", line):
                raise ValidationError(f"{BASELINE_FILE}: {line!r} is not a commit SHA")
            return line
    return None


def published_status_changes(repo: Path) -> list[dict]:
    """What the public changelog shows: nothing until a baseline commit is recorded, then one
    'Tracking began' entry plus every status change made after that commit."""
    baseline = read_baseline(repo)
    if baseline is None:
        return []
    return derive_status_changes(repo, baseline=baseline)


def _resolve_baseline(repo: Path, sha: str) -> str:
    try:
        full = _git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}").strip()
    except ValidationError as exc:
        raise ValidationError(f"{BASELINE_FILE}: commit {sha} does not exist in this repository") from exc
    if full not in _git(repo, "rev-list", "--first-parent", "HEAD").split():
        raise ValidationError(
            f"{BASELINE_FILE}: commit {sha} is not on the first-parent line of HEAD (use a commit on main)"
        )
    return full


def _tracking_began(repo: Path, full: str, impls: list[dict], stds: list[dict]) -> dict:
    day = datetime.fromtimestamp(int(_git(repo, "show", "-s", "--format=%ct", full)), UTC).date().isoformat()
    return changelog.entry(
        date=day,
        kind="tracking-began",
        subject_type="tracker",
        subject_id="tracker",
        title=(
            f"Tracking began {day}: {len(impls)} projects and {len(stds)} standards "
            "as recorded at that commit"
        ),
        detected_by="human",
        url=f"{REPO_URL}/commit/{full}",
        id_parts=(full[:12],),
    )


def derive_status_changes(repo: Path, baseline: str | None = None) -> list[dict]:
    """Confirmed status changes in the history of `repo`, oldest first. With `baseline` (a commit SHA),
    nothing before that commit is emitted; its state is the starting point and one 'tracking-began' entry
    stands for it. Without it, the first commit that has both files is the starting point."""
    if _git(repo, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise ValidationError(
            "the repository is a shallow clone: the full git history is needed to build the changelog "
            "(use fetch-depth: 0)"
        )
    entries: list[dict] = []
    state: dict | None = None
    if baseline is not None:
        full = _resolve_baseline(repo, baseline)
        impls, stds = _show(repo, full, FILES[0]), _show(repo, full, FILES[1])
        if impls is None or stds is None:
            raise ValidationError(f"{BASELINE_FILE}: commit {baseline} does not have both data files")
        _normalise(impls, stds)
        state = changelog.statuses_of(impls, stds)
        entries.append(_tracking_began(repo, full, impls, stds))
        log = _git(
            repo, "log", "--first-parent", "--reverse", "--format=%H %ct", f"{full}..HEAD", "--", *FILES
        )
    else:
        log = _git(repo, "log", "--first-parent", "--reverse", "--format=%H %ct", "--", *FILES)
    prev = state
    for line in log.splitlines():
        sha, ts = line.split()
        impls, stds = _show(repo, sha, FILES[0]), _show(repo, sha, FILES[1])
        if impls is None or stds is None:
            continue  # a commit that has only one of the files cannot be compared yet
        _normalise(impls, stds)
        day = datetime.fromtimestamp(int(ts), UTC).date().isoformat()
        if prev is not None:
            entries += changelog.diff_statuses(prev, impls, stds, day, ref=sha[:12])
        prev = changelog.statuses_of(impls, stds)
    if prev is None:
        raise ValidationError(
            "no commit in the history has both data/implementations.yaml and data/standards.yaml"
        )
    return entries
