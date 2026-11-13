"""Small helpers shared across modules."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from pqc_tracker.errors import ValidationError

CLOCK_ENV = "PQC_NOW"


def utcnow() -> datetime:
    """The one place the program reads the wall clock. `PQC_NOW` (an ISO 8601 UTC time) replaces it: the test
    suite always sets it, so no test depends on the day it runs, and CI sets it to other days to prove that."""
    fixed = os.environ.get(CLOCK_ENV)
    if fixed:
        return datetime.fromisoformat(fixed.replace("Z", "+00:00")).astimezone(UTC).replace(microsecond=0)
    return datetime.now(UTC).replace(microsecond=0)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_z(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc


def dumps_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the same directory so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def short_hash(*parts: str | None) -> str:
    joined = "\x1f".join("" if p is None else p for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
