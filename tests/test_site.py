import json
import re
import tempfile
import unittest
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from pqc_tracker import changelog as cl
from pqc_tracker import site
from pqc_tracker.validate import ROOT, validate_data_dir
from tests.helpers import claim, impl

NOW = datetime(2026, 11, 12, 8, 0, 0, tzinfo=UTC)


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in ("script", "style")

    def handle_endtag(self, tag):
        self.skip -= tag in ("script", "style")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def visible_text(html_text: str) -> str:
    p = Text()
    p.feed(html_text)
    return " ".join(p.parts)


class SiteBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = validate_data_dir(ROOT / "data")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "site"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ctx(self, **over):
        entries = over.pop("entries", [])
        kw = dict(
            implementations=self.d["implementations"],
            standards=self.d["standards"],
            snapshot=self.d["snapshot"],
            status=self.d["status"],
            entries=entries,
            now=NOW,
        )
        kw.update(over)
        return site.Context(**kw)

    def build(self, ctx=None):
        site.build_site(ctx or self.ctx(), self.out, ROOT / "schemas")

    def read(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")

    def test_required_files_exist(self):
        self.build()
        for rel in (
            "index.html",
            "standards/index.html",
            "changes/index.html",
            "methodology/index.html",
            "404.html",
            "feed.xml",
            "sitemap.xml",
            "robots.txt",
            "CNAME",
            "data/latest.json",
            "data/changelog.json",
        ):
            self.assertTrue((self.out / rel).exists(), rel)
        for i in self.d["implementations"]:
            self.assertTrue((self.out / "implementations" / i["id"] / "index.html").exists())
        self.assertEqual(self.read("CNAME").strip(), "pqc.silastron.com")

    def test_matrix_is_in_the_html_without_javascript(self):
        self.build()
        text = visible_text(self.read("index.html"))
        for name in (
            "OpenSSL",
            "BoringSSL",
            "AWS-LC",
            "wolfSSL",
            "liboqs",
            "Botan",
            "Bouncy Castle",
            "Go standard library",
            "OpenJDK",
            "rustls",
            "NSS",
            "OpenSSH",
        ):
            self.assertIn(name, text)
        self.assertIn("Supported", text)
        self.assertIn("No statement found", text)

    def test_status_is_text_not_only_colour(self):
        self.build()
        html_text = self.read("index.html")
        badges = re.findall(r'<span class="badge s-(\w[\w-]*)">(.*?)</span></td>', html_text)
        self.assertGreater(len(badges), 40)
        for status, inner in badges:
            self.assertIn(site.STATUS_LABELS[status], inner)

    def test_no_third_party_resources_or_inline_script(self):
        self.build()
        for p in self.out.rglob("*.html"):
            t = p.read_text(encoding="utf-8")
            self.assertNotRegex(t, r'(src|href)="https?://[^"]*\.(js|css|woff2?)"', p)
            self.assertEqual(re.findall(r"<script(?![^>]*(?:src=|application/ld\+json))", t), [], p)
            self.assertNotIn("<form", t)
            self.assertNotIn("style=", t)
        for p in (self.out / "assets").iterdir():
            self.assertNotRegex(p.read_text(), r"https?://", p)

    def test_every_page_has_canonical_description_og_and_footer(self):
        self.build()
        for p in self.out.rglob("*.html"):
            t = p.read_text(encoding="utf-8")
            self.assertRegex(t, r'<link rel="canonical" href="https://pqc\.silastron\.com/', p)
            self.assertIn('<meta name="description"', t)
            self.assertIn('property="og:title"', t)
            for needle in (
                "Last verified:",
                "Last collected:",
                "Join the Orbit",
                "https://silastron.com/newsletter/",
                "https://pulse.silastron.com",
                "https://github.com/Mehrn0ush/pqc",
                site.ESSAY_URL,
            ):
                self.assertIn(needle, t, (p, needle))

    def test_home_has_dataset_jsonld(self):
        self.build()
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', self.read("index.html"), re.S)
        ld = json.loads(m.group(1))
        self.assertEqual(ld["@type"], "Dataset")
        self.assertEqual(ld["license"], "https://creativecommons.org/licenses/by/4.0/")

    def test_tables_have_headers_and_captions(self):
        self.build()
        for rel in ("index.html", "standards/index.html", "implementations/openssl/index.html"):
            t = self.read(rel)
            self.assertEqual(t.count("<table"), t.count("<caption>"), rel)
            self.assertIn('<th scope="col">', t)
            self.assertIn('<th scope="row">', t)

    def test_home_shows_only_five_recent_changes(self):
        entries = [
            {
                "id": f"{n:016x}",
                "date": f"2026-11-{n:02d}",
                "kind": "release",
                "subject_type": "implementation",
                "subject_id": "openssl",
                "title": f"OpenSSL: new release {n}",
                "detected_by": "machine",
            }
            for n in range(10, 0, -1)
        ]
        self.build(self.ctx(entries=entries))
        home = self.read("index.html")
        self.assertEqual(len(re.findall(r"new release \d+", home)), 5)
        self.assertEqual(len(re.findall(r"new release \d+", self.read("changes/index.html"))), 10)

    def test_machine_entries_labelled_as_unreviewed(self):
        e = {
            "id": "a" * 16,
            "date": "2026-11-10",
            "kind": "release",
            "subject_type": "implementation",
            "subject_id": "openssl",
            "title": "OpenSSL: new release 9",
            "detected_by": "machine",
        }
        self.build(self.ctx(entries=[e]))
        self.assertIn("effect on statuses not yet reviewed", self.read("changes/index.html"))

    def test_stale_notice_when_last_collection_failed(self):
        status = {
            "schema_version": "1.0.0",
            "status": "failed",
            "last_good_collected_at": "2026-11-11T07:42:48Z",
            "failed_at": "2026-11-12T06:00:00Z",
            "error": "boom",
        }
        self.build(self.ctx(status=status))
        for rel in ("index.html", "standards/index.html"):
            self.assertIn("Data stale since 2026-11-11", self.read(rel))

    def test_stale_notice_when_snapshot_is_old(self):
        self.build(self.ctx(now=datetime(2026, 11, 20, tzinfo=UTC)))
        self.assertIn("Data stale since 2026-11-11", self.read("index.html"))

    def test_no_stale_notice_when_fresh(self):
        self.build()
        self.assertNotIn("Data stale", self.read("index.html"))

    def test_feed_is_wellformed_atom(self):
        import xml.etree.ElementTree as ET

        e = {
            "id": "a" * 16,
            "date": "2026-11-10",
            "kind": "release",
            "subject_type": "implementation",
            "subject_id": "openssl",
            "title": "OpenSSL & <friends>",
            "detected_by": "machine",
            "url": "https://example.org/?a=1&b=2",
        }
        self.build(self.ctx(entries=[e]))
        root = ET.fromstring(self.read("feed.xml"))
        self.assertTrue(root.tag.endswith("feed"))
        self.assertEqual(len(root.findall("{http://www.w3.org/2005/Atom}entry")), 1)

    def test_public_data_files(self):
        self.build()
        latest = json.loads(self.read("data/latest.json"))
        self.assertEqual(len(latest["implementations"]), 12)
        self.assertIn("datatracker", latest["standards"][0])
        self.assertEqual(json.loads(self.read("data/changelog.json"))["schema_version"], "1.0.0")

    def test_no_scores_or_rankings_in_output(self):
        self.build()
        for p in self.out.rglob("*.html"):
            t = visible_text(p.read_text(encoding="utf-8")).lower()
            self.assertNotRegex(t, r"\b(score|grade|ranking:|rank #)\b", p)

    def test_html_escaping(self):
        impls = [dict(i) for i in self.d["implementations"]]
        impls[0] = {**impls[0], "name": "<script>alert(1)</script>"}
        self.build(self.ctx(implementations=impls))
        self.assertNotIn("<script>alert", self.read("index.html"))

    def test_fips_206_phrasing_names_nist_page_date_and_sources(self):
        self.build()
        text = " ".join(visible_text(self.read("standards/index.html")).split())
        self.assertRegex(
            text,
            r"NIST's project page describes this as in development \(checked 2026-\d\d-\d\d\); "
            r"no draft publication was found in",
        )
        self.assertIn("csrc.nist.gov: drafts-open-for-comment", text)

    def test_sitemap_lists_all_pages(self):
        self.build()
        sm = self.read("sitemap.xml")
        self.assertEqual(sm.count("<loc>"), 4 + 12)

    def test_status_change_flows_into_published_changelog(self):
        base = cl.statuses_of(self.d["implementations"], self.d["standards"])
        base["implementations"]["go"]["slhdsa"] = "not-checked"
        new = cl.diff_statuses(base, self.d["implementations"], self.d["standards"], "2026-11-12")
        self.assertEqual(len(new), 1)
        self.build(self.ctx(entries=cl.merge_for_publication(new)))
        self.assertIn("Confirmed by a person", self.read("implementations/go/index.html"))


class CellRenderingTests(unittest.TestCase):
    """How the richer claim model shows up in the static HTML."""

    def build(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = validate_data_dir(ROOT / "data")
        algs = {
            "mlkem": claim(scope="hybrid-only", scheme="X25519MLKEM768"),
            "mldsa": claim(
                evidence_strength="inferred",
                strength_reason="Only a bug title mentions it.",
                since_version=None,
                since_note="No versioned releases.",
            ),
            "slhdsa": {
                "status": "no-statement-found",
                "checked_on": "2026-11-11",
                "checked_sources": ["https://example.org/changelog", "https://example.org/api"],
                "note": "Nothing found.",
            },
        }
        ctx = site.Context([impl(algs=algs)], d["standards"], d["snapshot"], d["status"], [], NOW)
        out = Path(tmp.name)
        site.build_site(ctx, out, ROOT / "schemas")
        return (out / "index.html").read_text(), (out / "implementations" / "x" / "index.html").read_text()

    def test_hybrid_only_is_labelled_in_text(self):
        home, page = self.build()
        for html_text in (home, page):
            text = visible_text(html_text)
            self.assertIn("Supported, hybrid only", text)
            self.assertIn("only as X25519MLKEM768", text)

    def test_inferred_cells_show_a_marker_and_the_reason(self):
        home, page = self.build()
        self.assertIn("† inferred", visible_text(home))
        self.assertIn("Only a bug title mentions it.", visible_text(page))

    def test_missing_version_is_never_blank(self):
        home, page = self.build()
        self.assertIn("version not stated", visible_text(home))
        self.assertIn("No versioned releases.", visible_text(page))

    def test_no_statement_found_lists_sources_and_date(self):
        _, page = self.build()
        text = visible_text(page)
        self.assertIn("Sources searched, 2026-11-11", text)
        self.assertIn("example.org/changelog", text)
        self.assertIn('href="https://example.org/api"', page)

    def test_hybrid_column_meaning_in_header_tooltip_and_on_project_page(self):
        home, page = self.build()
        self.assertRegex(home, r'<th scope="col" title="Hybrid key exchange means TLS 1.3')
        self.assertIn("For OpenSSH it means SSH key exchange.", visible_text(page))
        self.assertIn('title="Hybrid key exchange means TLS 1.3', page)


if __name__ == "__main__":
    unittest.main()
