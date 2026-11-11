"""Static site generator. Every page is complete HTML at build time; JavaScript is optional."""

from __future__ import annotations

import html
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

from pqc_tracker.config import (
    ALGORITHMS,
    ESSAY_LABEL,
    ESSAY_URL,
    EVIDENCE_TYPE_LABELS,
    HYBRID_COLUMN_HELP,
    ISSUES_URL,
    NEWSLETTER_URL,
    PULSE_URL,
    REPO_URL,
    SILASTRON_URL,
    SITE_NAME,
    SITE_URL,
    STALE_AFTER_HOURS,
    STANDARD_STATUS_LABELS,
    STATUS_LABELS,
)
from pqc_tracker.util import dumps_json, iso_z, parse_iso_z

STATIC = Path(__file__).parent / "static"
STATUS_SYMBOL = {
    "supported": "✓",
    "experimental": "◐",
    "planned": "◔",
    "not-supported": "✕",
    "not-checked": "·",
    "no-statement-found": "?",
}
KIND_LABEL = {
    "release": "New release",
    "draft-revision": "Draft revision",
    "draft-state": "Draft state",
    "status-change": "Status change",
}
NAV = [
    ("/", "Readiness"),
    ("/standards/", "Standards"),
    ("/changes/", "Changes"),
    ("/methodology/", "Methodology"),
]
DASH = "—"


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


@dataclass
class Context:
    implementations: list[dict]
    standards: list[dict]
    snapshot: dict | None
    status: dict | None
    entries: list[dict]  # merged changelog, newest first
    now: datetime

    @property
    def releases(self) -> dict:
        return (self.snapshot or {}).get("releases", {})

    @property
    def drafts(self) -> dict:
        return (self.snapshot or {}).get("drafts", {})

    @property
    def collected_at(self) -> str | None:
        return self.snapshot["collected_at"] if self.snapshot else None

    @property
    def last_verified(self) -> str:
        dates = [
            c.get("verified_on") or c.get("checked_on")
            for i in self.implementations
            for c in i["algorithms"].values()
        ]
        dates = [d for d in dates if d]
        dates += [s["verified_on"] for s in self.standards]
        return max(dates)

    @property
    def stale_since(self) -> str | None:
        """Date of the last good collection when the data is stale, else None."""
        if self.snapshot is None:
            return "never"
        last_good = self.collected_at
        failed = self.status is not None and self.status.get("status") == "failed"
        too_old = (self.now - parse_iso_z(last_good)).total_seconds() > STALE_AFTER_HOURS * 3600
        return last_good[:10] if (failed or too_old) else None

    @property
    def impl_names(self) -> dict[str, str]:
        return {i["id"]: i["name"] for i in self.implementations}


# ---------------------------------------------------------------- shared fragments


def badge(status: str, *, hybrid_only: bool = False) -> str:
    if hybrid_only:
        # Text label as well as colour and shape: hybrid-only is not full support.
        return (
            f'<span class="badge s-{esc(status)} s-hybrid"><span aria-hidden="true">◑ </span>'
            f"{esc(STATUS_LABELS[status])}, hybrid only</span>"
        )
    return (
        f'<span class="badge s-{esc(status)}"><span aria-hidden="true">{STATUS_SYMBOL[status]} </span>'
        f"{esc(STATUS_LABELS[status])}</span>"
    )


def cell_badge(c: dict) -> str:
    """Status badge plus scheme (hybrid-only) and the visible 'inferred' marker."""
    out = badge(c["status"], hybrid_only=c.get("scope") == "hybrid-only")
    if c.get("scheme"):
        out += f'<span class="scheme">only as {esc(c["scheme"])}</span>'
    if c.get("evidence_strength") == "inferred":
        out += f'<span class="inferred" title="{esc(c["strength_reason"])}">† inferred</span>'
    return out


def since_text(c: dict) -> str:
    if c["status"] not in ("supported", "experimental"):
        return ""
    return f"since {esc(c['since_version'])}" if c.get("since_version") else "version not stated"


def std_badge(status: str) -> str:
    return f'<span class="badge t-{esc(status)}">{esc(STANDARD_STATUS_LABELS[status])}</span>'


def stale_notice(ctx: Context) -> str:
    since = ctx.stale_since
    if since is None:
        return ""
    if since == "never":
        msg = "No data has been collected yet."
    else:
        msg = f"Data stale since {esc(since)}. The last collection did not complete or is overdue; figures below are from the last good snapshot."
    return f'<p class="notice" role="status"><strong>Data notice.</strong> {msg}</p>'


def header(path: str) -> str:
    items = []
    for href, label in NAV:
        cur = ' aria-current="page"' if href == path else ""
        items.append(f'<li><a href="{href}"{cur}>{esc(label)}</a></li>')
    return (
        '<a class="skip-link" href="#main">Skip to content</a>'
        '<header class="site-header">'
        '<p class="brand"><a href="/">Silastron PQC Tracker</a></p>'
        '<p class="eyebrow">Post-quantum cryptography readiness</p>'
        f'<nav aria-label="Main"><ul>{"".join(items)}</ul></nav></header>'
    )


def footer(ctx: Context) -> str:
    collected = ctx.collected_at[:10] if ctx.collected_at else "never"
    return (
        "<footer>"
        f"<p>Last verified: <strong>{esc(ctx.last_verified)}</strong> (most recent human check of any entry). "
        f"Last collected: <strong>{esc(collected)}</strong> (automated release and draft data).</p>"
        "<ul>"
        f'<li><a href="{esc(ESSAY_URL)}" rel="noopener">{esc(ESSAY_LABEL)}</a></li>'
        f'<li><a href="{NEWSLETTER_URL}" rel="noopener">Join the Orbit</a></li>'
        f'<li><a href="{PULSE_URL}" rel="noopener">Silastron Security Pulse</a></li>'
        f'<li><a href="{REPO_URL}" rel="noopener">Repository</a></li>'
        f'<li><a href="{ISSUES_URL}" rel="noopener">Report an error</a></li>'
        "</ul>"
        f'<p>A <a href="{SILASTRON_URL}" rel="noopener">Silastron</a> research project. No tracking, no cookies, '
        "no third-party scripts. Code: Apache-2.0. Data: CC BY 4.0.</p>"
        "</footer>"
    )


def page(
    ctx: Context,
    path: str,
    title: str,
    description: str,
    body: str,
    *,
    jsonld: dict | None = None,
    robots: str | None = None,
) -> str:
    full_title = (
        f"{title} | {SITE_NAME}" if path != "/" else f"{SITE_NAME}: can you use post-quantum crypto yet?"
    )
    canonical = SITE_URL + path
    ld = ""
    if jsonld:
        ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/")}</script>'
    rb = f'<meta name="robots" content="{esc(robots)}">' if robots else ""
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'self'; "
        "script-src 'self'; img-src data:; base-uri 'none'; form-action 'none'\">"
        f"<title>{esc(full_title)}</title>"
        f'<meta name="description" content="{esc(description)}">{rb}'
        f'<link rel="canonical" href="{esc(canonical)}">'
        '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 16 16%27%3E'
        '%3Crect width=%2716%27 height=%2716%27 rx=%273%27 fill=%27%2312182a%27/%3E%3Ccircle cx=%278%27 cy=%278%27 r=%275%27 fill=%27%23d889ae%27/%3E%3C/svg%3E">'
        '<link rel="alternate" type="application/atom+xml" title="Changelog" href="/feed.xml">'
        '<link rel="stylesheet" href="/assets/style.css">'
        f'<meta property="og:site_name" content="{esc(SITE_NAME)}">'
        '<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{esc(full_title)}">'
        f'<meta property="og:description" content="{esc(description)}">'
        f'<meta property="og:url" content="{esc(canonical)}">'
        '<meta name="twitter:card" content="summary">'
        f"{ld}</head><body>"
        f'{header(path)}<main id="main">{stale_notice(ctx)}{body}</main>{footer(ctx)}'
        '<script src="/assets/app.js" defer></script></body></html>\n'
    )


def provenance_line(ctx: Context) -> str:
    collected = ctx.collected_at[:10] if ctx.collected_at else "never"
    return (
        f'<p class="provenance">Statuses last checked by a person: {esc(ctx.last_verified)}. '
        f"Release and draft data collected: {esc(collected)}. Every status links to the evidence behind it.</p>"
    )


def legend() -> str:
    defs = {
        "supported": "shipped, with a primary source",
        "experimental": "available but marked experimental or prototype",
        "planned": "announced by the project, not shipped",
        "not-supported": "stated by the project as not available",
        "not-checked": "nobody has looked yet",
        "no-statement-found": "we looked and found no primary source; this is not a statement that it is unsupported",
    }
    items = "".join(f"<li>{badge(k)} {esc(v)}</li>" for k, v in defs.items())
    items += (
        f"<li>{badge('supported', hybrid_only=True)} works only as the named hybrid scheme, not on its own</li>"
        '<li><span class="inferred">† inferred</span> concluded from indirect evidence; the reason is shown</li>'
    )
    return f'<ul class="legend" aria-label="Status legend">{items}</ul>'


# ---------------------------------------------------------------- pages


def changes_list(ctx: Context, entries: list[dict], *, link_subject: bool = True) -> str:
    if not entries:
        return "<p>No changes recorded yet.</p>"
    out = ['<ul class="changes">']
    for e in entries:
        subject = esc(e["title"])
        if e["subject_type"] == "implementation" and link_subject:
            subject = f'<a href="/implementations/{esc(e["subject_id"])}/">{subject}</a>'
        elif e["subject_type"] == "standard" and link_subject:
            subject = f'<a href="/standards/#{esc(e["subject_id"])}">{subject}</a>'
        who = (
            "Confirmed by a person"
            if e["detected_by"] == "human"
            else "Detected automatically; effect on statuses not yet reviewed"
        )
        src = f' · <a href="{esc(e["url"])}" rel="noopener">Source</a>' if e.get("url") else ""
        out.append(
            f'<li><time datetime="{esc(e["date"])}">{esc(e["date"])}</time> '
            f'<span class="badge">{esc(KIND_LABEL[e["kind"]])}</span> {subject}'
            f'<span class="meta">{esc(who)}{src}</span></li>'
        )
    out.append("</ul>")
    return "".join(out)


def hybrid_title(alg: str) -> str:
    return f' title="{esc(HYBRID_COLUMN_HELP)}"' if alg == "hybrid_kex" else ""


def release_date(rel: dict, *, verb: bool = False) -> str:
    """Official dates are shown plainly; a tag-commit date is labelled approximate."""
    d = esc(rel["published_at"])
    if rel.get("date_source") == "tag-commit":
        return f"about {d} (approximate, from the tagged commit)" if verb else f"{d} (approximate)"
    return f"published {d}" if verb else d


def matrix(ctx: Context) -> str:
    head = "".join(
        f'<th scope="col"{hybrid_title(a)}>{esc(ALGORITHMS[a][0])}<br><span class="when">{esc(ALGORITHMS[a][1])}</span></th>'
        for a in ALGORITHMS
    )
    rows = []
    for impl in sorted(ctx.implementations, key=lambda i: i["name"].lower()):
        rel = ctx.releases.get(impl["id"])
        statuses = " ".join(sorted({c["status"] for c in impl["algorithms"].values()}))
        cells = []
        for alg in ALGORITHMS:
            c = impl["algorithms"][alg]
            since = f'<span class="since">{since_text(c)}</span>' if since_text(c) else ""
            cells.append(f"<td>{cell_badge(c)}{since}</td>")
        latest = (
            f'<span class="when">latest {esc(rel["tag"])}'
            + (f", {release_date(rel)}" if rel.get("published_at") else "")
            + "</span>"
            if rel
            else ""
        )
        rows.append(
            f'<tr data-kind="{esc(impl["kind"])}" data-name="{esc(impl["name"].lower())}" '
            f'data-statuses="{esc(statuses)}" data-released="{esc((rel or {}).get("published_at") or "")}">'
            f'<th scope="row"><a href="/implementations/{esc(impl["id"])}/">{esc(impl["name"])}</a>'
            f'<span class="when">{esc(impl["kind"])}</span>{latest}</th>{"".join(cells)}</tr>'
        )
    return (
        '<div id="matrix-controls" class="filters"></div>'
        '<div class="scroll" role="region" aria-label="Readiness matrix, scrollable" tabindex="0">'
        '<table id="matrix"><caption>Support status by project and algorithm. Statuses are listed alphabetically '
        f'by project; they are not a ranking.</caption><thead><tr><th scope="col">Project</th>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def home(ctx: Context) -> str:
    recent = ctx.entries[:5]
    n_unv = sum(
        1
        for i in ctx.implementations
        for c in i["algorithms"].values()
        if c["status"] == "no-statement-found"
    )
    n_unchecked = sum(
        1 for i in ctx.implementations for c in i["algorithms"].values() if c["status"] == "not-checked"
    )
    body = (
        "<h1>Can I use post-quantum crypto yet?</h1>"
        '<p class="lede">Silastron PQC Tracker shows which cryptographic libraries and runtimes support the NIST '
        "post-quantum algorithms ML-KEM, ML-DSA and SLH-DSA and hybrid key exchange, and where the underlying "
        "standards stand. Each status links to a primary source. Where we looked and found no source it says "
        "so, and that is not a statement that the feature is missing. There are no scores or rankings: "
        "statuses only.</p>"
        f"{provenance_line(ctx)}"
        "<h2>Readiness matrix</h2>"
        f"{legend()}{matrix(ctx)}"
        f'<p class="provenance">{n_unv} of {len(ctx.implementations) * len(ALGORITHMS)} cells are "no statement found" '
        f"and {n_unchecked} are not checked yet. "
        "Hybrid key exchange means TLS 1.3 unless a row says otherwise (OpenSSH rows describe SSH).</p>"
        "<h2>Recent changes</h2>"
        f'{changes_list(ctx, recent)}<p><a href="/changes/">Full changelog</a> · <a href="/feed.xml">Atom feed</a></p>'
        "<h2>More</h2>"
        '<div class="cols">'
        '<div class="card"><h3><a href="/standards/">Standards</a></h3><p>NIST FIPS and IETF drafts, with dates and sources.</p></div>'
        '<div class="card"><h3><a href="/changes/">Changes</a></h3><p>Dated log of releases, draft revisions and status changes.</p></div>'
        '<div class="card"><h3><a href="/methodology/">Methodology</a></h3><p>What each status means and how the data is checked.</p></div>'
        '<div class="card"><h3><a href="/data/latest.json">Data</a></h3><p>Open JSON under CC BY 4.0, with schemas.</p></div>'
        "</div>"
    )
    ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Silastron PQC Tracker: post-quantum cryptography support and standards status",
        "description": (
            "Support status of ML-KEM, ML-DSA, SLH-DSA and hybrid key exchange in twelve cryptographic libraries and "
            "runtimes, with NIST and IETF standards status and a dated changelog. Each status links to a primary source."
        ),
        "url": SITE_URL + "/",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "isAccessibleForFree": True,
        "creator": {"@type": "Organization", "name": "Silastron", "url": SILASTRON_URL},
        "dateModified": ctx.last_verified,
        "keywords": [
            "post-quantum cryptography",
            "ML-KEM",
            "ML-DSA",
            "SLH-DSA",
            "FIPS 203",
            "FIPS 204",
            "FIPS 205",
        ],
        "distribution": [
            {
                "@type": "DataDownload",
                "encodingFormat": "application/json",
                "contentUrl": f"{SITE_URL}/data/latest.json",
            },
            {
                "@type": "DataDownload",
                "encodingFormat": "application/json",
                "contentUrl": f"{SITE_URL}/data/changelog.json",
            },
        ],
    }
    return page(
        ctx,
        "/",
        "Readiness",
        "Which crypto libraries and runtimes support ML-KEM, ML-DSA, SLH-DSA and hybrid post-quantum key exchange, "
        "with evidence links, standards status and a dated changelog.",
        body,
        jsonld=ld,
    )


def datatracker_flag(std: dict, d: dict | None) -> str:
    if not d:
        return ""
    live_rfc = d["state"] == "rfc"
    if live_rfc and std["status"] != "rfc-published":
        return "Datatracker now shows an RFC; this entry has not been reviewed yet."
    if not live_rfc and std["status"] == "rfc-published":
        return "Datatracker does not show an RFC; this entry needs review."
    return ""


def source_label(url: str) -> str:
    u = urlparse(url)
    last = u.path.rstrip("/").rsplit("/", 1)[-1]
    return f"{u.hostname}: {last}" if last else str(u.hostname)


def nist_statement(s: dict) -> str:
    """What NIST itself says about an in-development item, where it says it, and what we searched."""
    if not s.get("stated_status"):
        return ""
    page = f'<a href="{esc(s["stated_url"])}" rel="noopener">project page</a>'
    out = f"NIST's {page} describes this as {esc(s['stated_status'])} (checked {esc(s['checked_on'])})"
    if s.get("no_draft_found"):
        links = ", ".join(
            f'<a href="{esc(u)}" rel="noopener">{esc(source_label(u))}</a>' for u in s["checked_sources"]
        )
        out += f"; no draft publication was found in {links}"
    return f'<span class="since">{out}. Quote: “{esc(s["stated_quote"])}”</span>'


def standards_page(ctx: Context) -> str:
    def row(s: dict) -> str:
        d = ctx.drafts.get(s.get("datatracker_name", ""))
        live = ""
        if d:
            live = f"Datatracker: {esc(d['rfc'] or ('-' + d['rev']))}"
            if d.get("iesg_state") and not d["rfc"]:
                live += f", {esc(d['iesg_state'])}"
            live = f'<span class="since">{live}</span>'
            flag = datatracker_flag(s, d)
            if flag:
                live += f'<span class="since">{esc(flag)}</span>'
        status = std_badge(s["status"]) + (
            f' <span class="since">{esc(s["rfc"])}</span>' if s.get("rfc") else ""
        )
        note = nist_statement(s) + (f'<span class="since">{esc(s["note"])}</span>' if s.get("note") else "")
        date = esc(s["status_date"]) if s["status_date"] else DASH
        return (
            f'<tr id="{esc(s["id"])}"><th scope="row">{esc(s["title"])}{note}</th>'
            f"<td>{esc(s.get('group', s['body']).upper() if s['body'] == 'IETF' else 'NIST')}</td>"
            f"<td>{status}{live}</td><td>{date}</td>"
            f'<td><a href="{esc(s["source_url"])}" rel="noopener">Source</a></td><td>{esc(s["verified_on"])}</td></tr>'
        )

    def table(label: str, items: list[dict]) -> str:
        return (
            f'<div class="scroll" role="region" aria-label="{esc(label)}, scrollable" tabindex="0"><table>'
            f"<caption>{esc(label)}</caption><thead><tr>"
            '<th scope="col">Standard</th><th scope="col">Body</th><th scope="col">Status</th>'
            '<th scope="col">Status date</th><th scope="col">Source</th><th scope="col">Last verified</th></tr></thead>'
            f"<tbody>{''.join(row(s) for s in items)}</tbody></table></div>"
        )

    nist = [s for s in ctx.standards if s["body"] == "NIST"]
    ietf = [s for s in ctx.standards if s["body"] == "IETF"]
    active = sorted((s for s in ietf if s["status"] != "rfc-published"), key=lambda s: (s["group"], s["id"]))
    published = sorted(
        (s for s in ietf if s["status"] == "rfc-published"), key=lambda s: (s["group"], s["id"])
    )

    def active_row(s: dict) -> str:
        d = ctx.drafts.get(s["datatracker_name"])
        rev = f"-{esc(d['rev'])}" if d else "not collected yet"
        updated = esc(d["updated_at"]) if d else DASH
        live = ""
        if d and d.get("iesg_state"):
            live = f'<span class="since">Datatracker: {esc(d["iesg_state"])}</span>'
        flag = datatracker_flag(s, d)
        if flag:
            live += f'<span class="since">{esc(flag)}</span>'
        note = f'<span class="since">{esc(s["note"])}</span>' if s.get("note") else ""
        return (
            f'<tr id="{esc(s["id"])}"><th scope="row">{esc(s["title"])}{note}</th><td>{esc(s["group"].upper())}</td>'
            f"<td>{std_badge(s['status'])}{live}</td><td>{rev}</td><td>{updated}</td>"
            f'<td><a href="{esc(s["source_url"])}" rel="noopener">Source</a></td><td>{esc(s["verified_on"])}</td></tr>'
        )

    active_table = (
        '<div class="scroll" role="region" aria-label="Active IETF drafts, scrollable" tabindex="0"><table>'
        "<caption>Active IETF drafts in the TLS, LAMPS and PQUIP working groups, with the latest revision "
        "and the date the Datatracker last updated each one.</caption><thead><tr>"
        '<th scope="col">Draft</th><th scope="col">Group</th><th scope="col">Status</th>'
        '<th scope="col">Revision</th><th scope="col">Last updated</th>'
        '<th scope="col">Source</th><th scope="col">Last verified</th></tr></thead>'
        f"<tbody>{''.join(active_row(s) for s in active)}</tbody></table></div>"
        if active
        else "<p>No active drafts are tracked.</p>"
    )
    body = (
        "<h1>Standards status</h1>"
        '<p class="lede">Where the NIST post-quantum standards and the relevant IETF documents stand. '
        "IETF entries are compared with the Datatracker every day; a difference is flagged here but only a person "
        "changes the status shown.</p>"
        f"{provenance_line(ctx)}<h2>NIST</h2>{table('NIST standards and projects', nist)}"
        f"<h2>IETF active drafts ({len(active)})</h2>{active_table}"
        f'<details id="published-rfcs"><summary><h2>Published RFCs ({len(published)})</h2></summary>'
        f"{table('IETF documents already published as RFCs', published)}</details>"
    )
    return page(
        ctx,
        "/standards/",
        "Standards status",
        "Status of FIPS 203, 204, 205, FIPS 206, HQC, NIST IR 8547 and the IETF TLS, LAMPS and PQUIP "
        "post-quantum documents, with dates and sources.",
        body,
    )


def changes_page(ctx: Context) -> str:
    body = (
        "<h1>Changes</h1>"
        '<p class="lede">Newest first. Entries marked as detected automatically are facts from release feeds '
        "and the IETF Datatracker; they do not change any status. Status changes appear only after a person has "
        "reviewed the evidence.</p>"
        f'<p><a href="/feed.xml">Atom feed</a> · <a href="/data/changelog.json">changelog.json</a></p>'
        f"{changes_list(ctx, ctx.entries)}"
    )
    return page(
        ctx,
        "/changes/",
        "Changes",
        "Dated log of new releases, IETF draft revisions and confirmed status changes.",
        body,
    )


def since_cell(c: dict) -> str:
    if c["status"] not in ("supported", "experimental"):
        return DASH
    if c.get("since_version"):
        return esc(c["since_version"])
    return f'version not stated<span class="when">{esc(c["since_note"])}</span>'


def evidence_cell(c: dict) -> str:
    if c["status"] == "not-checked":
        return "Not checked yet"
    if c["status"] == "no-statement-found":
        links = "".join(
            f'<li><a href="{esc(u)}" rel="noopener">{esc(u.removeprefix("https://"))}</a></li>'
            for u in c["checked_sources"]
        )
        return f'Sources searched, {esc(c["checked_on"])}:<ul class="sources">{links}</ul>'
    kind = EVIDENCE_TYPE_LABELS[c["evidence_type"]]
    return (
        f'<a href="{esc(c["evidence_url"])}" rel="noopener">Evidence</a>'
        f'<span class="when">{esc(kind)}, {esc(c["evidence_strength"])}</span>'
    )


def note_cell(c: dict) -> str:
    parts = []
    if c.get("evidence_strength") == "inferred":
        parts.append(f"<strong>Inferred:</strong> {esc(c['strength_reason'])}")
    if c.get("scope") == "hybrid-only":
        parts.append(f"Hybrid only: available only as {esc(c['scheme'])}.")
    if c.get("note"):
        parts.append(esc(c["note"]))
    return " ".join(parts)


def implementation_page(ctx: Context, impl: dict) -> str:
    rel = ctx.releases.get(impl["id"])
    rows = []
    for alg, (label, std) in ALGORITHMS.items():
        c = impl["algorithms"][alg]
        rows.append(
            f'<tr><th scope="row"{hybrid_title(alg)}>{esc(label)}<span class="when">{esc(std)}</span></th>'
            f"<td>{cell_badge(c)}</td><td>{since_cell(c)}</td><td>{evidence_cell(c)}</td>"
            f"<td>{esc(c.get('verified_on') or c.get('checked_on') or '') or DASH}</td><td>{note_cell(c)}</td></tr>"
        )
    if rel:
        when = f", {release_date(rel, verb=True)}" if rel.get("published_at") else ""
        latest = (
            f'<p>Latest release found: <a href="{esc(rel["url"])}" rel="noopener">{esc(rel["tag"])}</a>{when}. '
            "A newer release does not change any status below until a person reviews it.</p>"
        )
    else:
        latest = "<p>No release data collected yet.</p>"
    history = [
        e for e in ctx.entries if e["subject_type"] == "implementation" and e["subject_id"] == impl["id"]
    ]
    repo = (
        f' · <a href="https://github.com/{esc(impl["repo"])}" rel="noopener">Repository</a>'
        if impl.get("repo")
        else ""
    )
    body = (
        f"<h1>{esc(impl['name'])}</h1>"
        f'<p class="lede">{esc(impl["kind"].capitalize())}. <a href="{esc(impl["homepage"])}" rel="noopener">Project site</a>{repo}</p>'
        f"{provenance_line(ctx)}<h2>Post-quantum support</h2>"
        f"<p>{esc(HYBRID_COLUMN_HELP)}</p>{legend()}"
        '<div class="scroll" role="region" aria-label="Support statuses, scrollable" tabindex="0"><table>'
        "<caption>Support status per algorithm, with evidence.</caption><thead><tr>"
        '<th scope="col">Algorithm</th><th scope="col">Status</th><th scope="col">Since version</th>'
        '<th scope="col">Evidence</th><th scope="col">Last verified</th><th scope="col">Note</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        f"<h2>Latest release</h2>{latest}"
        f"<h2>Change history</h2>{changes_list(ctx, history, link_subject=False)}"
        f'<p>Something wrong? <a href="{ISSUES_URL}/new/choose" rel="noopener">Report a status correction</a>.</p>'
    )
    return page(
        ctx,
        f"/implementations/{impl['id']}/",
        f"{impl['name']} post-quantum support",
        f"Post-quantum support status for {impl['name']}: ML-KEM, ML-DSA, SLH-DSA and hybrid key exchange, "
        "with evidence links, latest release and change history.",
        body,
    )


def methodology_page(ctx: Context) -> str:
    body = f"""
<h1>Methodology</h1>
<p class="lede">What the statuses mean, how data is collected and checked, and where it can be wrong.</p>
{provenance_line(ctx)}
<h2>What each status means</h2>
<dl>
<dt>{badge("supported")}</dt><dd>A release of the project includes the feature and a primary source says so (release notes, official documentation, a changelog or an API reference). "Since version" is the first version we found stating it, which may not be the true first version; where no version is given the cell says "version not stated" and why. Source code alone never earns this status.</dd>
<dt>{badge("experimental")}</dt><dd>Available, but the project itself calls it experimental, a prototype, or not for production. A header file or module with no statement of support level is shown here at most, marked inferred.</dd>
<dt>{badge("planned")}</dt><dd>A maintainer has announced it but it has not shipped. An open request in an issue tracker is not enough.</dd>
<dt>{badge("not-supported")}</dt><dd>The project explicitly states that it is not available. We never infer this from silence.</dd>
<dt>{badge("no-statement-found")}</dt><dd>We looked and found no primary source. The cell lists the date and every source searched. This is not a statement that the feature is missing: it may exist without being documented, or we may have looked in the wrong place.</dd>
<dt>{badge("not-checked")}</dt><dd>Nobody has looked yet.</dd>
<dt>{badge("supported", hybrid_only=True)}</dt><dd>The algorithm is available only inside the named hybrid scheme (for example ML-KEM inside X25519MLKEM768), not as a standalone primitive.</dd>
<dt><span class="inferred">† inferred</span></dt><dd>Every supported or experimental cell is tagged with an evidence type (release notes, official docs, changelog, API reference, source code or issue tracker) and a strength. "Stated" means the upstream source says the feature is supported. "Inferred" means we concluded it from indirect evidence, such as a bug-fix title or a header file; the one-line reason is shown next to the cell.</dd>
</dl>
<p>The matrix column "Hybrid key exchange" means TLS 1.3 groups such as X25519MLKEM768, except for OpenSSH, where it is SSH key exchange. Support for an algorithm inside a library does not mean a product built on that library has enabled it, and it does not mean FIPS validation.</p>
<h2>Two kinds of data</h2>
<ul>
<li><strong>Human-reviewed statuses.</strong> Written in <code>data/implementations.yaml</code> and <code>data/standards.yaml</code>. Each claim has an evidence URL and the date a person last read it.</li>
<li><strong>Machine-collected facts.</strong> Latest release tag and date per project, and latest revision and state per IETF draft, collected daily into <code>data/snapshots/latest.json</code>.</li>
</ul>
<p>Automation detects change; a person confirms what it means. A new release or draft revision never changes a status by itself. It adds a changelog entry marked as automatically detected and opens a GitHub issue labelled <code>review-needed</code> with the link. Status changes appear in the changelog only after the YAML files change; they are derived from the git history of those two files, so the whole log can be rebuilt from a clone of the repository and does not depend on the live site.</p>
<h2>If collection fails</h2>
<p>If any source errors or returns malformed data, the whole run is discarded, the last good snapshot stays, the workflow fails, and every page shows a "data stale since" notice. Partial data is never published.</p>
<h2>Sources and licences</h2>
<ul>
<li>Release data: GitHub Releases and Git tags APIs, the Go, Botan, OpenSSH, Bouncy Castle and NSS release pages, per project as shown on each project page. Release dates come from the project's own release page or announcement (Go, Botan, Bouncy Castle, OpenSSH and NSS) or its GitHub release. Only OpenJDK's official release pages refuse automated requests, so its date is the tagged commit's date and is shown as approximate.</li>
<li>Draft data: the IETF Datatracker.</li>
<li>Standards status: NIST CSRC pages and the Datatracker, linked per row.</li>
<li>Evidence: each project's own release notes and documentation, linked per cell. We link to sources and quote only short factual phrases; their text stays under their own licences.</li>
<li>This site's data is CC BY 4.0 and its code is Apache-2.0.</li>
</ul>
<h2>Limits</h2>
<ul>
<li>This is a snapshot of what we have read, not an audit. Twelve projects and four capabilities only.</li>
<li>Several projects do not publish dated release notes for post-quantum features; where so, "since version" is left blank.</li>
<li>Statuses describe the upstream project. Distributions, vendors and product builds may differ.</li>
<li>NIST status pages can lag or be reorganised. FIPS 206 and the HQC standard are shown with NIST's own wording, the page that says it, the date we checked and the NIST listings searched for a draft. Not finding a draft in those listings is not proof that none exists.</li>
<li>Entries can be out of date between human reviews. The "Last verified" date on each row says when.</li>
</ul>
<h2>Data files</h2>
<ul>
<li><a href="/data/latest.json">/data/latest.json</a>: current statuses with latest releases and draft states. Schema versions are in <code>schema_version</code>.</li>
<li><a href="/data/changelog.json">/data/changelog.json</a>: full changelog.</li>
<li><a href="/schemas/implementations.schema.json">JSON Schemas</a> for the input and output files are published under <code>/schemas/</code>.</li>
</ul>
<h2>Report an error</h2>
<p>Open a <a href="{ISSUES_URL}/new/choose" rel="noopener">status correction</a> issue with the evidence link, or propose the change as a pull request (see <a href="{REPO_URL}/blob/main/CONTRIBUTING.md" rel="noopener">CONTRIBUTING</a>). Corrections without a primary source cannot change a status.</p>
"""
    return page(
        ctx,
        "/methodology/",
        "Methodology",
        "What each status means, how the data is collected and verified, sources and licences, and limits of the data.",
        body,
    )


def not_found(ctx: Context) -> str:
    body = (
        "<h1>Page not found</h1><p>That page does not exist. Try the "
        '<a href="/">readiness matrix</a>, <a href="/standards/">standards</a> or <a href="/changes/">changes</a>.</p>'
    )
    return page(ctx, "/404.html", "Page not found", "Page not found.", body, robots="noindex")


# ---------------------------------------------------------------- data files


def latest_json(ctx: Context) -> dict:
    impls = []
    for i in sorted(ctx.implementations, key=lambda x: x["id"]):
        impls.append(
            {
                "id": i["id"],
                "name": i["name"],
                "kind": i["kind"],
                "homepage": i["homepage"],
                "repo": i.get("repo"),
                "latest_release": ctx.releases.get(i["id"]),
                "algorithms": i["algorithms"],
                "url": f"{SITE_URL}/implementations/{i['id']}/",
            }
        )
    stds = []
    for s in sorted(ctx.standards, key=lambda x: x["id"]):
        item = dict(s)
        item["datatracker"] = ctx.drafts.get(s.get("datatracker_name", ""))
        stds.append(item)
    return {
        "schema_version": "1.0.0",
        "license": "CC BY 4.0",
        "generated_at": iso_z(ctx.now),
        "last_verified": ctx.last_verified,
        "last_collected": ctx.collected_at,
        "stale_since": None if ctx.stale_since is None else ctx.stale_since,
        "algorithms": {k: {"name": v[0], "standard": v[1]} for k, v in ALGORITHMS.items()},
        "implementations": impls,
        "standards": stds,
    }


def feed_xml(ctx: Context) -> str:
    entries = ctx.entries[:100]
    updated = (entries[0]["date"] if entries else ctx.last_verified) + "T00:00:00Z"
    out = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"<title>{xml_escape(SITE_NAME)} changelog</title>",
        f'<link href="{SITE_URL}/changes/"/><link rel="self" href="{SITE_URL}/feed.xml"/>',
        f"<id>{SITE_URL}/</id><updated>{updated}</updated>",
        "<author><name>Silastron</name></author>",
    ]
    for e in entries:
        link = e.get("url") or f"{SITE_URL}/changes/"
        who = (
            "confirmed by a person"
            if e["detected_by"] == "human"
            else "detected automatically, not yet reviewed"
        )
        out.append(
            f"<entry><title>{xml_escape(e['title'])}</title><id>tag:pqc.silastron.com,2026:{e['id']}</id>"
            f'<updated>{e["date"]}T00:00:00Z</updated><link href="{xml_escape(link)}"/>'
            f"<summary>{xml_escape(KIND_LABEL[e['kind']] + ' (' + who + ')')}</summary></entry>"
        )
    out.append("</feed>\n")
    return "\n".join(out)


def sitemap(ctx: Context, paths: list[str]) -> str:
    lastmod = ctx.now.date().isoformat()
    urls = "".join(
        f"<url><loc>{xml_escape(SITE_URL + p)}</loc><lastmod>{lastmod}</lastmod></url>" for p in paths
    )
    return f'<?xml version="1.0" encoding="utf-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'


# ---------------------------------------------------------------- build


def build_site(ctx: Context, out_dir: Path, schema_dir: Path) -> list[str]:
    """Write the complete site to out_dir. Returns the list of page paths (for the sitemap)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    pages: dict[str, str] = {
        "/": home(ctx),
        "/standards/": standards_page(ctx),
        "/changes/": changes_page(ctx),
        "/methodology/": methodology_page(ctx),
    }
    for impl in ctx.implementations:
        pages[f"/implementations/{impl['id']}/"] = implementation_page(ctx, impl)
    for path, text in pages.items():
        target = out_dir / path.strip("/") / "index.html" if path != "/" else out_dir / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (out_dir / "404.html").write_text(not_found(ctx), encoding="utf-8")
    assets = out_dir / "assets"
    assets.mkdir()
    for name in ("style.css", "app.js"):
        shutil.copy(STATIC / name, assets / name)
    data = out_dir / "data"
    data.mkdir()
    (data / "latest.json").write_text(dumps_json(latest_json(ctx)), encoding="utf-8")
    (data / "changelog.json").write_text(
        dumps_json({"schema_version": "1.0.0", "entries": ctx.entries}), encoding="utf-8"
    )
    schemas = out_dir / "schemas"
    schemas.mkdir()
    for f in sorted(schema_dir.glob("*.schema.json")):
        shutil.copy(f, schemas / f.name)
    (out_dir / "feed.xml").write_text(feed_xml(ctx), encoding="utf-8")
    (out_dir / "sitemap.xml").write_text(sitemap(ctx, list(pages)), encoding="utf-8")
    (out_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8"
    )
    (out_dir / "CNAME").write_text("pqc.silastron.com\n", encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return list(pages)
