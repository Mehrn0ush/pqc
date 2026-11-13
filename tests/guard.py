"""Keeps tests independent of live data and the wall clock.

Installed by tests/__init__.py. Two rules:

1. A test may not open a file under the repository's data/ directory. Tests use tests/fixtures/data, which
   Collect never touches. The one exception is the explicitly named `real_data_shape()` context in
   tests/real_data.py, used by tests that only validate the shape of the real data.
2. A test never reads the wall clock: PQC_NOW is set for the whole run (default below), and
   pqc_tracker.util.utcnow() honours it. CI overrides it to other days.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_DATA = ROOT / "data"
DEFAULT_CLOCK = "2026-11-12T08:00:00Z"

_allowed = 0
_installed = False
_real_open = builtins.open


class RealDataAccess(AssertionError):
    pass


def _check(file) -> None:
    if _allowed or not isinstance(file, str | os.PathLike):
        return
    try:
        path = Path(os.fspath(file)).resolve()
    except (OSError, ValueError):
        return
    if path == REAL_DATA or REAL_DATA in path.parents:
        raise RealDataAccess(
            f"a test opened {path.relative_to(ROOT)}: tests must use tests/fixtures/data, or wrap "
            "shape-only checks of the real data in tests.real_data.real_data_shape()"
        )


def _guarded_open(file, *args, **kwargs):
    _check(file)
    return _real_open(file, *args, **kwargs)


@contextlib.contextmanager
def allow_real_data():
    global _allowed
    _allowed += 1
    try:
        yield
    finally:
        _allowed -= 1


def install() -> None:
    global _installed
    os.environ.setdefault("PQC_NOW", DEFAULT_CLOCK)
    if _installed:
        return
    builtins.open = _guarded_open
    io.open = _guarded_open
    _installed = True
