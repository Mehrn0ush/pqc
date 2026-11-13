"""The only way for a test to look at the repository's real data/ files.

Use it for shape checks only: schemas, cross-file consistency, the rules in validate.py. Never assert on a
specific date, version or status here, because Collect and people change those every day."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pqc_tracker.validate import ROOT, validate_data_dir
from tests.guard import allow_real_data

# Far enough ahead that "verified_on is in the future" can never fire, whenever the suite runs.
FAR_FUTURE = date(2099, 1, 1)


def real_data_shape():
    """Context manager that permits reading data/. The name is the point: grep for it."""
    return allow_real_data()


def validate_real_data() -> dict:
    with real_data_shape():
        return validate_data_dir(ROOT / "data", today=FAR_FUTURE)


def read_real_text(relative: str) -> str:
    with real_data_shape():
        return (Path(ROOT) / "data" / relative).read_text(encoding="utf-8")
