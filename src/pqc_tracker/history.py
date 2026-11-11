"""Confirmed status changes, derived from the git history of the two human-edited YAML files.

Deterministic and rebuildable from a fresh clone: no network, no published site. Each commit on the
first-parent line of main that changes data/implementations.yaml or data/standards.yaml is compared
with the previous such commit; every changed status becomes one 'status-change' entry dated by that
commit. The first commit that has both files is the baseline and produces no entries."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from pqc_tracker import changelog
from pqc_tracker.errors import ValidationError

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


def derive_status_changes(repo: Path) -> list[dict]:
    """All confirmed status changes in the history of `repo`, oldest first."""
    if _git(repo, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise ValidationError(
            "the repository is a shallow clone: the full git history is needed to build the changelog "
            "(use fetch-depth: 0)"
        )
    log = _git(repo, "log", "--first-parent", "--reverse", "--format=%H %ct", "--", *FILES)
    entries: list[dict] = []
    baseline: dict | None = None
    for line in log.splitlines():
        sha, ts = line.split()
        impls, stds = _show(repo, sha, FILES[0]), _show(repo, sha, FILES[1])
        if impls is None or stds is None:
            continue  # a commit that has only one of the files cannot be compared yet
        _normalise(impls, stds)
        day = datetime.fromtimestamp(int(ts), UTC).date().isoformat()
        if baseline is not None:
            entries += changelog.diff_statuses(baseline, impls, stds, day, ref=sha[:12])
        baseline = changelog.statuses_of(impls, stds)
    if baseline is None:
        raise ValidationError(
            "no commit in the history has both data/implementations.yaml and data/standards.yaml"
        )
    return entries
