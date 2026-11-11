"""Post-deploy check: the live site must serve the build that was just deployed.

Fetches the live /build.json and /data/latest.json (cache-busting query, retried while Pages and the CDN
catch up) and compares the commit, the implementations hash and every status with the files that were built."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

USER_AGENT = "silastron-pqc-tracker-smoke (+https://pqc.silastron.com)"


def statuses(latest: dict) -> dict[str, str]:
    """Every status the site publishes, keyed by what it describes."""
    out = {}
    for i in latest["implementations"]:
        for alg, c in i["algorithms"].items():
            out[f"{i['id']}.{alg}"] = c["status"] + (" (expired planned)" if c.get("expired_planned") else "")
    for s in latest["standards"]:
        out[f"standard:{s['id']}"] = s["status"]
    return out


def compare(built_build: dict, built_latest: dict, live_build: dict, live_latest: dict) -> list[str]:
    """Differences between what was built and what is live. Empty means the deployment is the build."""
    problems = []
    for key in ("commit", "implementations_sha256", "built_at"):
        if built_build.get(key) != live_build.get(key):
            problems.append(f"build.json {key}: built {built_build.get(key)!r}, live {live_build.get(key)!r}")
    a, b = statuses(built_latest), statuses(live_latest)
    for k in sorted(a.keys() | b.keys()):
        if a.get(k) != b.get(k):
            problems.append(f"status {k}: built {a.get(k)!r}, live {b.get(k)!r}")
    return problems


def fetch_json(url: str) -> dict:
    if urlparse(url).scheme != "https":
        raise ValueError("only https URLs are fetched")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - https checked above
        return json.loads(r.read().decode("utf-8"))


def run(
    site_dir: Path,
    base_url: str,
    timeout: float = 300,
    interval: float = 15,
    fetch: Callable[[str], dict] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Retry until the live site matches the build or `timeout` seconds pass. Returns the last problems."""
    built_build = json.loads((site_dir / "build.json").read_text(encoding="utf-8"))
    built_latest = json.loads((site_dir / "data" / "latest.json").read_text(encoding="utf-8"))
    deadline = clock() + timeout
    attempt = 0
    while True:
        attempt += 1
        stamp = time.time_ns()
        try:
            live_build = fetch(f"{base_url}/build.json?cb={stamp}")
            live_latest = fetch(f"{base_url}/data/latest.json?cb={stamp}")
            problems = compare(built_build, built_latest, live_build, live_latest)
        except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
            problems = [f"could not read the live site: {exc}"]
        if not problems:
            log(f"ok after {attempt} attempt(s): live site is commit {built_build['commit'][:12]}")
            return []
        log(f"attempt {attempt}: {len(problems)} difference(s), first: {problems[0]}")
        if clock() + interval > deadline:
            return problems
        sleep(interval)
