"""Check that evidence and source URLs still resolve. Runs in CI only, never in the collector.

Hard failures: 404 and 410 (the evidence is gone), DNS/connection errors, non-HTTPS URLs.
Warnings: 401/403/429/5xx, because sites commonly block automated clients or have outages."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HARD = {404, 410}
UA = "Mozilla/5.0 (compatible; silastron-pqc-linkcheck; +https://pqc.silastron.com)"


def urls_to_check(implementations: list[dict], standards: list[dict]) -> dict[str, list[str]]:
    """url -> where it is used."""
    out: dict[str, list[str]] = {}
    for i in implementations:
        out.setdefault(i["homepage"], []).append(f"{i['id']} homepage")
        for alg, c in i["algorithms"].items():
            if c.get("evidence_url"):
                out.setdefault(c["evidence_url"], []).append(f"{i['id']}.{alg}")
            for u in c.get("checked_sources", []):
                out.setdefault(u, []).append(f"{i['id']}.{alg} checked_sources")
    for s in standards:
        out.setdefault(s["source_url"], []).append(s["id"])
    return out


def default_status(url: str) -> int:
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": UA}), timeout=30) as resp:  # noqa: S310
                return resp.status
        except HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                return exc.code
            last = exc
        except (URLError, TimeoutError, OSError) as exc:
            last = exc
        time.sleep(2**attempt)
    if isinstance(last, HTTPError):
        return last.code
    raise OSError(str(last))


def check(
    implementations: list[dict],
    standards: list[dict],
    status_of: Callable[[str], int] = default_status,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    items = sorted(urls_to_check(implementations, standards).items())

    def probe(item):
        url, used = item
        where = ", ".join(used)
        if not url.startswith("https://"):
            return "error", f"{url} ({where}): not HTTPS"
        try:
            code = status_of(url)
        except OSError as exc:
            return "error", f"{url} ({where}): {exc}"
        if code in HARD:
            return "error", f"{url} ({where}): HTTP {code}"
        if code >= 400:
            return "warning", f"{url} ({where}): HTTP {code}"
        return "ok", ""

    with ThreadPoolExecutor(max_workers=8) as pool:
        for kind, msg in pool.map(probe, items):
            if kind == "error":
                errors.append(msg)
            elif kind == "warning":
                warnings.append(msg)
    return errors, warnings
