"""Schema and semantic validation of every data file."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from pqc_tracker.errors import ValidationError
from pqc_tracker.util import load_json, load_yaml

ROOT = Path(__file__).resolve().parents[2]

SCHEMA_FILES = {
    "implementations": "implementations.schema.json",
    "standards": "standards.schema.json",
    "snapshot": "snapshot.schema.json",
    "changelog": "changelog.schema.json",
    "collection-status": "collection-status.schema.json",
}


def schema_errors(kind: str, data: Any, schema_dir: Path) -> list[str]:
    schema = load_json(schema_dir / SCHEMA_FILES[kind])
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    return [
        f"{kind}: {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))
    ]


def _dups(ids: list[str], what: str) -> list[str]:
    return [f"{what}: duplicate id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]


def semantic_errors(impls: list[dict], stds: list[dict], snapshot: dict | None, today: date) -> list[str]:
    errs: list[str] = []
    errs += _dups([i["id"] for i in impls], "implementations")
    errs += _dups([s["id"] for s in stds], "standards")
    errs += _dups([s["datatracker_name"] for s in stds if "datatracker_name" in s], "datatracker_name")
    for i in impls:
        for alg, c in i["algorithms"].items():
            if date.fromisoformat(c["verified_on"]) > today:
                errs.append(f"{i['id']}.{alg}: verified_on is in the future")
            if c["status"] == "unverified" and c.get("since_version"):
                errs.append(f"{i['id']}.{alg}: unverified claims cannot carry since_version")
    for s in stds:
        if date.fromisoformat(s["verified_on"]) > today:
            errs.append(f"{s['id']}: verified_on is in the future")
        if s["status"] == "rfc-published" and "rfc" not in s:
            errs.append(f"{s['id']}: rfc-published needs an rfc number")
    # A snapshot that lags the YAML (a newly added project, say) is normal until the next Collect run,
    # and the site shows "no release data collected yet" for it. Only unknown draft names are an error.
    if snapshot is not None:
        names = {s["datatracker_name"] for s in stds if "datatracker_name" in s}
        errs += [f"snapshot: draft not tracked {k!r}" for k in snapshot["drafts"] if k not in names]
    return errs


def validate_data_dir(data_dir: Path, schema_dir: Path | None = None, today: date | None = None) -> dict:
    """Validate all files; return the loaded documents or raise ValidationError listing every problem."""
    schema_dir = schema_dir or ROOT / "schemas"
    today = today or date.today()
    impls = load_yaml(data_dir / "implementations.yaml")
    stds = load_yaml(data_dir / "standards.yaml")
    snap_path = data_dir / "snapshots" / "latest.json"
    log_path = data_dir / "changelog.json"
    status_path = data_dir / "collection-status.json"
    snapshot = load_json(snap_path) if snap_path.exists() else None
    log = load_json(log_path) if log_path.exists() else {"schema_version": "1.0.0", "entries": []}
    status = load_json(status_path) if status_path.exists() else None
    errs = schema_errors("implementations", impls, schema_dir) + schema_errors("standards", stds, schema_dir)
    if snapshot is not None:
        errs += schema_errors("snapshot", snapshot, schema_dir)
    errs += schema_errors("changelog", log, schema_dir)
    if status is not None:
        errs += schema_errors("collection-status", status, schema_dir)
    if not errs:
        errs += semantic_errors(impls, stds, snapshot, today)
        errs += _dups([e["id"] for e in log["entries"]], "changelog")
    if errs:
        raise ValidationError("\n".join(errs))
    return {
        "implementations": impls,
        "standards": stds,
        "snapshot": snapshot,
        "changelog": log,
        "status": status,
    }
