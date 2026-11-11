"""Validate Atom feeds against the RELAX NG Compact schema in RFC 4287, Appendix B.

Needs lxml and rnc2rng from PyPI (requirements-feed-check.lock) and the network, to read the RFC. Run in
CI after `pqc-tracker build`:

    python .github/scripts/validate_atom.py dist/site/feed.xml

It validates every file named on the command line and also a populated feed made by the site generator
from fixture entries, because the real feed may have no entries."""

from __future__ import annotations

import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import rnc2rng
from lxml import etree

from pqc_tracker import site

RFC_URL = "https://www.rfc-editor.org/rfc/rfc4287.txt"
HEADING = "Appendix B.  RELAX NG Compact Schema"


def atom_schema() -> etree.RelaxNG:
    with urllib.request.urlopen(RFC_URL, timeout=60) as r:  # noqa: S310 - fixed https URL
        text = r.read().decode("utf-8").replace("\f", "")
    start = text.rindex(HEADING)  # the first hit is the table of contents
    end = text.index("Authors' Addresses", start)
    body = text[text.index("# -*- rnc -*-", start) : end]
    lines = [
        line.strip()
        for line in body.splitlines()
        if not re.match(r"^(Nottingham & Sayre|RFC 4287 +Atom Format)", line)
    ]
    rnc = "\n".join(lines) + "\n"
    xml = rnc2rng.dumps(rnc2rng.loads(rnc))
    # `namespace local = ""` becomes xmlns:local="", which XML forbids; the schema's `local:*` is already
    # written out as ns="" so the declaration is not needed.
    xml = re.sub(r'\s+xmlns:local=""', "", xml)
    return etree.RelaxNG(etree.fromstring(xml.encode("utf-8")))


def fixture_feed() -> bytes:
    base = {"subject_type": "implementation", "subject_id": "openssl", "detected_by": "machine"}
    entries = [
        {
            "id": "b" * 16,
            "date": "2026-11-12",
            "kind": "planned-expired",
            "title": "X, SLH-DSA: 'planned' statement expired & shown as <No statement found>",
            "url": "https://example.org/old?a=1&b=2",
            **base,
        },
        {
            "id": "a" * 16,
            "date": "2026-11-10",
            "kind": "release",
            "title": "OpenSSL: new release 4.1.0",
            **base,
        },
    ]
    ctx = site.Context([], [], None, None, entries, datetime(2026, 11, 12, tzinfo=UTC))
    return site.feed_xml(ctx).encode("utf-8")


def check(schema: etree.RelaxNG, name: str, data: bytes) -> bool:
    doc = etree.fromstring(data)
    ok = schema.validate(doc)
    entries = len(doc.findall("{http://www.w3.org/2005/Atom}entry"))
    print(f"{'PASS' if ok else 'FAIL'}: {name} ({entries} entries)")
    for err in schema.error_log:
        print(f"  line {err.line}: {err.message}")
    return ok


def main(paths: list[str]) -> int:
    schema = atom_schema()
    results = [check(schema, "populated fixture feed", fixture_feed())]
    results += [check(schema, p, Path(p).read_bytes()) for p in paths]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
