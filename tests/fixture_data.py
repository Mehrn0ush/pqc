"""Frozen data for tests: a copy of the repository data as of 2026-11-13, with the collection dates pinned.
Collect never touches it, so a test built on it gives the same answer on any day."""

from __future__ import annotations

from pathlib import Path

from pqc_tracker.validate import validate_data_dir

FIXTURE_DATA = Path(__file__).parent / "fixtures" / "data"


def load_fixture_data(today=None) -> dict:
    return validate_data_dir(FIXTURE_DATA, today=today)
