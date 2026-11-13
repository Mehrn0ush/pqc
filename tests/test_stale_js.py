"""stale.js: the notice a visitor sees when the page's data is more than 48 hours old by their own clock.

The script runs under Node's `vm` with an injected Date and a minimal fake document, so the clock is exactly
what each test says. The tests need Node (preinstalled on GitHub runners)."""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pqc_tracker import site
from pqc_tracker.validate import ROOT
from tests.fixture_data import load_fixture_data

SCRIPT = site.STATIC / "stale.js"
NODE = shutil.which("node")
BUILT = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
COLLECTED = BUILT - timedelta(hours=1)

RUNNER = r"""
const vm = require("vm"), fs = require("fs");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const inserted = [];
const main = {firstChild: "FIRST", insertBefore(node, ref) { inserted.push({text: node.textContent, className: node.className, role: node.attrs.role, ref}); }};
const footer = input.footer === null ? null : {dataset: input.footer};
const sandbox = {
  document: {
    querySelector: (sel) => (sel === "footer[data-collected]" ? footer : null),
    getElementById: (id) => (id === "main" ? main : null),
    createElement: () => ({attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }}),
  },
  Date: {now: () => Date.parse(input.now), parse: Date.parse},
  Math, isNaN,
};
vm.runInNewContext(fs.readFileSync(input.script, "utf8"), sandbox);
process.stdout.write(JSON.stringify(inserted));
"""


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@unittest.skipUnless(NODE, "needs Node")
class StaleNoticeTests(unittest.TestCase):
    def run_script(self, now, collected=COLLECTED, built=BUILT, footer=True):
        data = {
            "script": str(SCRIPT),
            "now": iso(now),
            "footer": {"collected": iso(collected), "built": iso(built)} if footer else None,
        }
        out = subprocess.run(
            [NODE, "-e", RUNNER], input=json.dumps(data), capture_output=True, text=True, check=True
        )
        return json.loads(out.stdout)

    def test_fresh_page_shows_nothing(self):
        self.assertEqual(self.run_script(COLLECTED + timedelta(hours=2)), [])

    def test_47_hours_shows_nothing(self):
        self.assertEqual(self.run_script(COLLECTED + timedelta(hours=47)), [])

    def test_exactly_48_hours_shows_nothing(self):
        self.assertEqual(self.run_script(COLLECTED + timedelta(hours=48)), [])

    def test_49_hours_shows_the_notice_with_the_date(self):
        (n,) = self.run_script(COLLECTED + timedelta(hours=49))
        self.assertEqual(
            n["text"],
            "This page was last updated 2026-11-13. Automated collection or publishing may have stopped.",
        )
        self.assertEqual((n["className"], n["role"], n["ref"]), ("notice", "status", "FIRST"))

    def test_a_clock_more_than_a_year_ahead_is_ignored(self):
        self.assertEqual(self.run_script(BUILT + timedelta(days=367)), [])
        self.assertEqual(len(self.run_script(BUILT + timedelta(days=364))), 1)

    def test_a_clock_more_than_a_year_behind_is_ignored(self):
        self.assertEqual(self.run_script(BUILT - timedelta(days=400)), [])

    def test_a_clock_before_the_collection_is_ignored(self):
        self.assertEqual(self.run_script(COLLECTED - timedelta(hours=5)), [])

    def test_the_date_shown_is_the_collected_date_not_the_build_date(self):
        old = BUILT - timedelta(days=5)
        (n,) = self.run_script(BUILT + timedelta(hours=1), collected=old)
        self.assertIn(old.strftime("%Y-%m-%d"), n["text"])

    def test_no_footer_stamps_means_no_notice_and_no_error(self):
        self.assertEqual(self.run_script(BUILT + timedelta(days=3), footer=False), [])

    def test_garbage_stamps_mean_no_notice_and_no_error(self):
        data = {"script": str(SCRIPT), "now": iso(BUILT), "footer": {"collected": "never", "built": "x"}}
        out = subprocess.run(
            [NODE, "-e", RUNNER], input=json.dumps(data), capture_output=True, text=True, check=True
        )
        self.assertEqual(json.loads(out.stdout), [])


class StaleScriptContractTests(unittest.TestCase):
    def test_under_one_kilobyte(self):
        self.assertLess(SCRIPT.stat().st_size, 1024)

    def test_no_network_no_storage_no_eval(self):
        src = SCRIPT.read_text()
        for banned in (
            "fetch(",
            "XMLHttpRequest",
            "localStorage",
            "sessionStorage",
            "cookie",
            "eval(",
            "innerHTML",
        ):
            self.assertNotIn(banned, src)

    def test_every_page_loads_it_from_the_same_origin_and_has_no_inline_script_code(self):
        d = load_fixture_data()
        ctx = site.Context(d["implementations"], d["standards"], d["snapshot"], d["status"], [], BUILT)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            site.build_site(ctx, out, ROOT / "schemas")
            self.assertTrue((out / "assets/stale.js").exists())
            for page in out.rglob("*.html"):
                html = page.read_text()
                self.assertIn('<script src="/assets/stale.js" defer></script>', html, page)
                for m in re.finditer(r"<script([^>]*)>(.*?)</script>", html, re.S):
                    attrs, body = m.groups()
                    if 'src="' in attrs:
                        self.assertFalse(body.strip(), page)
                    else:
                        self.assertIn("application/ld+json", attrs, page)  # data, not code
                self.assertIn("script-src 'self'", html)

    def test_footer_carries_the_collected_and_build_times_the_script_reads(self):
        d = load_fixture_data()
        ctx = site.Context(d["implementations"], d["standards"], d["snapshot"], d["status"], [], BUILT)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            site.build_site(ctx, out, ROOT / "schemas")
            html = (out / "index.html").read_text()
            self.assertIn(
                '<footer data-collected="2026-11-11T07:42:48Z" data-built="2026-11-13T12:00:00Z">', html
            )

    def test_matrix_heading_repeats_the_collected_date_for_visitors_without_javascript(self):
        d = load_fixture_data()
        ctx = site.Context(d["implementations"], d["standards"], d["snapshot"], d["status"], [], BUILT)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            site.build_site(ctx, out, ROOT / "schemas")
            self.assertIn(
                '<h2>Readiness matrix <span class="stamp">collected 2026-11-11</span></h2>',
                (out / "index.html").read_text(),
            )

    def test_no_snapshot_means_no_stamps_and_no_notice_target(self):
        d = load_fixture_data()
        ctx = site.Context(d["implementations"], d["standards"], None, None, [], BUILT)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            site.build_site(ctx, out, ROOT / "schemas")
            html = (out / "index.html").read_text()
            self.assertNotIn("data-collected", html)
            self.assertIn("collected never", html)


if __name__ == "__main__":
    unittest.main()
