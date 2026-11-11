"""Shared test helpers: a fake Fetcher that serves recorded fixtures. Tests never touch the network."""

from __future__ import annotations

import json
from pathlib import Path

from pqc_tracker.errors import CollectionError

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


class FakeFetcher:
    """Maps URL -> response. Unknown URLs raise, like a real network error would."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    def _get(self, url: str):
        if url not in self.routes:
            raise CollectionError(f"HTTP 404 for GET {url}")
        value = self.routes[url]
        if isinstance(value, Exception):
            raise value
        return value

    def get_json(self, url: str):
        self.calls.append(("GET", url, None))
        return self._get(url)

    def get_text(self, url: str) -> str:
        self.calls.append(("GET", url, None))
        return self._get(url)

    def request_json(self, method: str, url: str, body: dict | None = None):
        self.calls.append((method, url, body))
        if method == "GET":
            return self._get(url)
        return self.routes.get(f"{method} {url}", {"number": 1})


def claim(**kw):
    """A valid 'supported' claim; override fields as needed."""
    base = {
        "status": "supported",
        "scope": "standalone",
        "since_version": "1.0",
        "evidence_type": "release-notes",
        "evidence_strength": "stated",
        "evidence_url": "https://example.org/e",
        "verified_on": "2026-11-11",
    }
    base.update(kw)
    keep_null = base["status"] in ("supported", "experimental")
    return {k: v for k, v in base.items() if v is not None or (k == "since_version" and keep_null)}


def impl(id="x", name="X", algs=None, source=None):
    claim = {"status": "not-checked"}
    algs = algs or {}
    return {
        "id": id,
        "name": name,
        "kind": "library",
        "homepage": "https://example.org/",
        "release_source": source or {"type": "github_release", "repo": "o/x"},
        "algorithms": {a: algs.get(a, claim) for a in ("mlkem", "mldsa", "slhdsa", "hybrid_kex")},
    }


def std(id="s", status="final", **kw):
    base = {
        "id": id,
        "title": f"Standard {id}",
        "body": "NIST",
        "status": status,
        "status_date": "2024-08-13",
        "source_url": "https://example.org/s",
        "verified_on": "2026-11-11",
    }
    base.update(kw)
    return base
