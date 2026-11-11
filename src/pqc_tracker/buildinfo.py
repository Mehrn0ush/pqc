"""What a build was made from, so a deployment can be checked against the commit it claims to be."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from pqc_tracker.errors import ValidationError
from pqc_tracker.history import git
from pqc_tracker.util import iso_z

SCHEMA_VERSION = "1.0.0"


def collect(repo: Path, data_dir: Path, now: datetime) -> dict:
    """The contents of /build.json: the commit built, when, and a hash of data/implementations.yaml."""
    commit = git(repo, "rev-parse", "HEAD").strip()
    path = data_dir / "implementations.yaml"
    if not path.exists():
        raise ValidationError(f"{path} does not exist")
    return {
        "schema_version": SCHEMA_VERSION,
        "commit": commit,
        "built_at": iso_z(now),
        "implementations_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
