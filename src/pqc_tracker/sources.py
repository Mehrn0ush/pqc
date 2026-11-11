"""Release collectors. Each returns {"tag", "published_at", "url"} or raises CollectionError.

They report facts only. They never decide what a release means for a support status."""

from __future__ import annotations

import html
import re
from datetime import date
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
    return {"tag": tag, "published_at": published[:10], "date_source": "official", "url": url}


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
    return {
        "tag": tag,
        "published_at": date[:10],
        "date_source": "tag-commit",
        "url": f"https://github.com/{repo}/tree/{quote(tag)}",
    }


def _plain(raw: str) -> str:
    """Page text with tags removed and whitespace collapsed."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))


def _iso(y: int, m: int, d: int, where: str) -> str:
    try:
        return date(y, m, d).isoformat()
    except ValueError as exc:
        raise CollectionError(f"{where}: invalid date") from exc


def _highest(found: list[tuple[tuple[int, ...], str, str]], where: str) -> tuple[str, str]:
    """found: (version key, tag, date). Returns the highest version's (tag, date)."""
    if not found:
        raise CollectionError(f"{where}: no release entry found")
    _, tag, published = max(found)
    return tag, published


_GO = re.compile(r"\bgo(\d+)\.(\d+)(?:\.(\d+))? \(released (\d{4})-(\d\d)-(\d\d)\)")


def go_release_history(fetcher: Fetcher, url: str) -> dict:
    """go.dev/doc/devel/release lists every release with its date."""
    where = "Go release history"
    text = _plain(fetcher.get_text(url))
    found = []
    for m in _GO.finditer(text):
        maj, minor, patch = int(m[1]), int(m[2]), int(m[3] or 0)
        tag = f"go{maj}.{minor}" + (f".{m[3]}" if m[3] else "")
        found.append(((maj, minor, patch), tag, _iso(int(m[4]), int(m[5]), int(m[6]), where)))
    tag, published = _highest(found, where)
    return {"tag": tag, "published_at": published, "date_source": "official", "url": f"{url}#{tag}"}


_BOTAN = re.compile(r"\bVersion (\d+)\.(\d+)\.(\d+), (\d{4})-(\d\d)-(\d\d)\b")


def botan_news(fetcher: Fetcher, url: str) -> dict:
    """botan.randombit.net/news.html: 'Version 3.14.1, 2026-11-06'. Unreleased versions have no date."""
    where = "Botan news"
    text = _plain(fetcher.get_text(url))
    found = [
        (
            (int(m[1]), int(m[2]), int(m[3])),
            f"{m[1]}.{m[2]}.{m[3]}",
            _iso(int(m[4]), int(m[5]), int(m[6]), where),
        )
        for m in _BOTAN.finditer(text)
    ]
    tag, published = _highest(found, where)
    return {"tag": tag, "published_at": published, "date_source": "official", "url": url}


_OPENSSH = re.compile(r"\bOpenSSH (\d+)\.(\d+)(?:p(\d+))? \((\d{4})-(\d\d)-(\d\d)\)")


def openssh_release_notes(fetcher: Fetcher, url: str) -> dict:
    """openssh.org/releasenotes.html headings: 'OpenSSH 10.6p2 (2026-11-05)'. The tag keeps the
    portable git tag spelling so the changelog does not see a new release when only the source changes."""
    where = "OpenSSH release notes"
    text = _plain(fetcher.get_text(url))
    found = []
    for m in _OPENSSH.finditer(text):
        maj, minor, p = int(m[1]), int(m[2]), int(m[3] or 1)
        found.append(((maj, minor, p), f"V_{maj}_{minor}_P{p}", _iso(int(m[4]), int(m[5]), int(m[6]), where)))
    tag, published = _highest(found, where)
    page = url.rsplit("/", 1)[0] + "/txt/release-" + tag[2:].replace("_P", "p").replace("_", ".", 1)
    return {"tag": tag, "published_at": published, "date_source": "official", "url": page}


_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        1,
    )
}
_BC_ENTRY = re.compile(r"Release: ([^\n]+?)\\?\n+Date: ([^\n]+)")


def _bc_date(raw: str, where: str) -> str | None:
    """'2026, 11th September.' or '2026, July 12th' -> ISO date. 'TBD' (unreleased) -> None."""
    low = raw.lower()
    year = re.match(r"\s*(\d{4})", low)
    month = next((n for name, n in _MONTHS.items() if name in low), None)
    day = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", low[year.end() :] if year else low)
    if "tbd" in low:
        return None
    if not (year and month and day):
        raise CollectionError(f"{where}: cannot read date {raw!r}")
    return _iso(int(year[1]), month, int(day[1]), where)


def bc_release_notes(fetcher: Fetcher, url: str) -> dict:
    """bc-java docs/releasenotes.md: 'Release: 1.86, 1.86.1' then 'Date: 2026, 11th September.'.
    The date belongs to the first (base) version listed. Entries dated TBD are not released."""
    where = "Bouncy Castle release notes"
    text = re.sub(r"<[^>]+>", "", fetcher.get_text(url))
    found = []
    for m in _BC_ENTRY.finditer(text):
        iso = _bc_date(m[2], where)
        v = re.search(r"\b(\d+)\.(\d+)\b", m[1])
        if iso is None or not v:
            continue
        found.append(((int(v[1]), int(v[2])), f"r{v[1]}rv{v[2]}", iso))
    tag, published = _highest(found, where)
    return {
        "tag": tag,
        "published_at": published,
        "date_source": "official",
        "url": "https://github.com/bcgit/bc-java/blob/main/docs/releasenotes.md",
    }


_NSS_LATEST = re.compile(r"NSS\s+(3\.\d+(?:\.\d+)?)\s+is the latest version of NSS", re.I)
_NSS_RELEASED = re.compile(
    r"Network Security Services \(NSS\) (3\.\d+(?:\.\d+)?) was released on (\d{1,2}) (\w+) (\d{4})"
)


def nss_release_notes(fetcher: Fetcher, url: str) -> dict:
    """Mozilla publishes NSS release notes only as web pages: the index names the latest version and
    that version's page says 'NSS 3.133 was released on 4 November 2026'."""
    m = _NSS_LATEST.search(_plain(fetcher.get_text(url)))
    if not m:
        raise CollectionError("NSS release notes: 'latest version' line not found")
    version = m.group(1)
    page = url.rsplit("/", 1)[0] + "/nss_" + version.replace(".", "_") + ".html"
    r = _NSS_RELEASED.search(_plain(fetcher.get_text(page)))
    if not r or r[1] != version or r[3].lower() not in _MONTHS:
        raise CollectionError(f"NSS {version} release notes: 'was released on' line not found")
    published = _iso(int(r[4]), _MONTHS[r[3].lower()], int(r[2]), "NSS release notes")
    return {"tag": f"NSS {version}", "published_at": published, "date_source": "official", "url": page}


_PAGE_COLLECTORS = {
    "go_release_history": go_release_history,
    "botan_news": botan_news,
    "openssh_release_notes": openssh_release_notes,
    "bc_release_notes": bc_release_notes,
    "nss_release_notes": nss_release_notes,
}


def collect_release(fetcher: Fetcher, impl: dict) -> dict:
    src = impl["release_source"]
    kind = src["type"]
    if kind == "github_release":
        return github_release(fetcher, src["repo"])
    if kind == "github_tags":
        return github_tags(fetcher, src["repo"], src["prefix"], src["tag_regex"])
    if kind in _PAGE_COLLECTORS:
        return _PAGE_COLLECTORS[kind](fetcher, src["url"])
    raise CollectionError(f"{impl['id']}: unknown release source {kind!r}")
