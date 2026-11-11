"""Release collectors. Each returns {"tag", "published_at", "url"} or raises CollectionError.

They report facts only. They never decide what a release means for a support status."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from pqc_tracker.errors import CollectionError
from pqc_tracker.http import Fetcher

API = "https://api.github.com"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _require(obj: Any, key: str, typ: type, where: str):
    if not isinstance(obj, dict) or not isinstance(obj.get(key), typ) or not obj[key]:
        raise CollectionError(f"{where}: missing or invalid {key!r}")
    return obj[key]


def github_release(fetcher: Fetcher, repo: str) -> dict:
    where = f"{repo} latest release"
    data = fetcher.get_json(f"{API}/repos/{repo}/releases/latest")
    tag = _require(data, "tag_name", str, where)
    published = _require(data, "published_at", str, where)
    url = _require(data, "html_url", str, where)
    if not _DATE.match(published) or not url.startswith("https://"):
        raise CollectionError(f"{where}: malformed date or url")
    return {"tag": tag, "published_at": published[:10], "url": url}


def _version_key(tag: str, regex: re.Pattern) -> tuple[int, ...] | None:
    m = regex.match(tag)
    if not m:
        return None
    return tuple(int(g) if g is not None else 0 for g in m.groups())


def github_tags(fetcher: Fetcher, repo: str, prefix: str, tag_regex: str) -> dict:
    """Highest tag matching tag_regex under prefix, by numeric version. Date is the tagged
    commit's date, an approximation of the release date."""
    where = f"{repo} tags"
    refs = fetcher.get_json(f"{API}/repos/{repo}/git/matching-refs/tags/{quote(prefix, safe='')}")
    if not isinstance(refs, list):
        raise CollectionError(f"{where}: expected a list")
    regex = re.compile(tag_regex)
    best: tuple[tuple[int, ...], str] | None = None
    for ref in refs:
        name = ref.get("ref", "") if isinstance(ref, dict) else ""
        if not name.startswith("refs/tags/"):
            raise CollectionError(f"{where}: malformed ref entry")
        tag = name[len("refs/tags/") :]
        key = _version_key(tag, regex)
        if key is not None and (best is None or key > best[0]):
            best = (key, tag)
    if best is None:
        raise CollectionError(f"{where}: no tag matched {tag_regex!r}")
    tag = best[1]
    commit = fetcher.get_json(f"{API}/repos/{repo}/commits/{quote(tag, safe='')}")
    date = (((commit or {}).get("commit") or {}).get("committer") or {}).get("date")
    if not isinstance(date, str) or not _DATE.match(date):
        raise CollectionError(f"{where}: no commit date for {tag}")
    return {"tag": tag, "published_at": date[:10], "url": f"https://github.com/{repo}/tree/{quote(tag)}"}


_NSS_LATEST = re.compile(r"NSS\s+(3\.\d+(?:\.\d+)?)\s+is the latest version of NSS", re.I)


def nss_release_notes(fetcher: Fetcher, url: str) -> dict:
    """Mozilla publishes NSS release notes only as web pages; read the 'latest version' line."""
    text = fetcher.get_text(url)
    m = _NSS_LATEST.search(re.sub(r"<[^>]+>", " ", text))
    if not m:
        raise CollectionError("NSS release notes: 'latest version' line not found")
    version = m.group(1)
    slug = "nss_" + version.replace(".", "_")
    return {
        "tag": f"NSS {version}",
        "published_at": None,
        "url": url.rsplit("/", 1)[0] + f"/{slug}.html",
    }


def collect_release(fetcher: Fetcher, impl: dict) -> dict:
    src = impl["release_source"]
    kind = src["type"]
    if kind == "github_release":
        return github_release(fetcher, src["repo"])
    if kind == "github_tags":
        return github_tags(fetcher, src["repo"], src["prefix"], src["tag_regex"])
    if kind == "nss_release_notes":
        return nss_release_notes(fetcher, src["url"])
    raise CollectionError(f"{impl['id']}: unknown release source {kind!r}")
