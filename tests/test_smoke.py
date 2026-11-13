import copy
import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pqc_tracker import buildinfo, cli, site, smoke
from pqc_tracker.util import iso_z, utcnow
from pqc_tracker.validate import ROOT
from tests.fixture_data import FIXTURE_DATA, load_fixture_data
from tests.helpers import impl, std
from tests.test_history import FixtureRepo

NOW = datetime(2026, 11, 12, 8, 0, 0, tzinfo=UTC)
SHA = "a" * 40


def build_files(commit=SHA, status="supported"):
    latest = {
        "implementations": [
            {
                "id": "x",
                "algorithms": {"mlkem": {"status": status}, "mldsa": {"status": "no-statement-found"}},
            }
        ],
        "standards": [{"id": "fips-203", "status": "final"}],
    }
    build = {
        "schema_version": "1.0.0",
        "commit": commit,
        "built_at": "2026-11-12T08:00:00Z",
        "implementations_sha256": "f" * 64,
    }
    return build, latest


class CompareTests(unittest.TestCase):
    def test_identical_is_ok(self):
        b, latest = build_files()
        self.assertEqual(smoke.compare(b, latest, copy.deepcopy(b), copy.deepcopy(latest)), [])

    def test_a_different_commit_or_hash_is_reported(self):
        b, latest = build_files()
        live = dict(b, commit="b" * 40, implementations_sha256="0" * 64)
        problems = smoke.compare(b, latest, live, latest)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("commit" in p for p in problems))

    def test_any_changed_status_is_reported(self):
        b, latest = build_files()
        _, other = build_files(status="planned")
        (p,) = smoke.compare(b, latest, b, other)
        self.assertIn("x.mlkem", p)
        self.assertIn("'supported'", p)

    def test_a_cell_or_standard_missing_on_the_live_site_is_reported(self):
        b, latest = build_files()
        live = copy.deepcopy(latest)
        del live["implementations"][0]["algorithms"]["mldsa"]
        live["standards"] = []
        self.assertEqual(len(smoke.compare(b, latest, b, live)), 2)

    def test_expiry_state_counts_as_a_difference(self):
        b, latest = build_files()
        live = copy.deepcopy(latest)
        live["implementations"][0]["algorithms"]["mldsa"]["expired_planned"] = {"expired_on": "2027-01-02"}
        self.assertEqual(len(smoke.compare(b, latest, b, live)), 1)


class RunTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.build, self.latest = build_files()
        (self.dir / "data").mkdir()
        (self.dir / "build.json").write_text(json.dumps(self.build))
        (self.dir / "data/latest.json").write_text(json.dumps(self.latest))
        self.t = 0.0
        self.urls = []

    def sleep(self, s):
        self.t += s

    def clock(self):
        return self.t

    def run_smoke(self, fetch, **kw):
        return smoke.run(
            self.dir,
            "https://live.example",
            fetch=fetch,
            sleep=self.sleep,
            clock=self.clock,
            log=lambda m: None,
            **kw,
        )

    def test_succeeds_once_the_live_site_catches_up(self):
        stale_build, stale_latest = build_files(commit="b" * 40, status="planned")

        def fetch(url):
            self.urls.append(url)
            old = len(self.urls) <= 4  # two attempts of two files
            if "/build.json" in url:
                return stale_build if old else self.build
            return stale_latest if old else self.latest

        self.assertEqual(self.run_smoke(fetch), [])
        self.assertEqual(len(self.urls), 6)
        self.assertEqual(self.t, 30)

    def test_every_request_has_a_cache_busting_query(self):
        def fetch(url):
            self.urls.append(url)
            return self.build if "/build.json" in url else self.latest

        self.run_smoke(fetch)
        self.assertTrue(all("?cb=" in u for u in self.urls))
        self.assertTrue(self.urls[0].startswith("https://live.example/build.json?cb="))
        self.assertTrue(self.urls[1].startswith("https://live.example/data/latest.json?cb="))

    def test_gives_up_after_the_timeout_and_reports_the_differences(self):
        stale_build, stale_latest = build_files(commit="b" * 40)
        calls = []

        def fetch(url):
            calls.append(url)
            return stale_build if "/build.json" in url else stale_latest

        problems = self.run_smoke(fetch, timeout=300, interval=15)
        self.assertTrue(any("commit" in p for p in problems))
        self.assertLessEqual(self.t, 300)
        self.assertGreaterEqual(len(calls) // 2, 20)  # retried for the whole five minutes

    def test_a_status_difference_alone_fails_the_run(self):
        _, other = build_files(status="experimental")
        problems = self.run_smoke(
            lambda url: self.build if "/build.json" in url else other, timeout=30, interval=15
        )
        self.assertEqual(len(problems), 1)

    def test_network_errors_are_retried_then_reported(self):
        def fetch(url):
            raise OSError("connection reset")

        problems = self.run_smoke(fetch, timeout=30, interval=15)
        self.assertIn("could not read the live site", problems[0])

    def test_http_urls_are_never_fetched(self):
        with self.assertRaises(ValueError):
            smoke.fetch_json("http://example.org/build.json")


class BuildInfoTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = FixtureRepo(self.root / "repo")
        self.commit = self.repo.commit([impl("a", "A")], [std()], "2026-01-10T12:00:00+00:00")
        self.data = load_fixture_data()

    def test_build_json_has_commit_time_and_data_hash(self):
        info = buildinfo.collect(self.repo.path, FIXTURE_DATA, NOW)
        self.assertEqual(info["commit"], self.commit)
        self.assertEqual(info["built_at"], "2026-11-12T08:00:00Z")
        self.assertEqual(
            info["implementations_sha256"],
            hashlib.sha256((FIXTURE_DATA / "implementations.yaml").read_bytes()).hexdigest(),
        )

    def test_site_writes_build_json_and_links_the_short_sha_in_every_footer(self):
        d = self.data
        info = {
            "schema_version": "1.0.0",
            "commit": SHA,
            "built_at": "2026-11-12T08:00:00Z",
            "implementations_sha256": "f" * 64,
        }
        ctx = site.Context(d["implementations"], d["standards"], d["snapshot"], d["status"], [], NOW, info)
        out = self.root / "site"
        site.build_site(ctx, out, ROOT / "schemas")
        self.assertEqual(json.loads((out / "build.json").read_text()), info)
        for page in out.rglob("*.html"):
            html = page.read_text()
            self.assertIn(
                f'<a href="https://github.com/Mehrn0ush/pqc/commit/{SHA}" rel="noopener"><code>aaaaaaa</code></a>',
                html,
                page,
            )

    def test_without_build_info_no_build_json_and_no_footer_note(self):
        d = self.data
        ctx = site.Context(d["implementations"], d["standards"], d["snapshot"], d["status"], [], NOW)
        out = self.root / "site"
        site.build_site(ctx, out, ROOT / "schemas")
        self.assertFalse((out / "build.json").exists())
        self.assertNotIn("Build <a", (out / "index.html").read_text())

    def test_cli_build_writes_build_json_for_the_given_repository(self):
        out = self.root / "cli-site"
        args = ["--data-dir", str(FIXTURE_DATA), "build", "--out", str(out), "--repo", str(self.repo.path)]
        self.assertEqual(cli.main(args), 0)
        info = json.loads((out / "build.json").read_text())
        self.assertEqual(info["commit"], self.commit)
        self.assertEqual(info["built_at"], iso_z(utcnow()))  # the injected clock, PQC_NOW


class VendoredAtomSchemaTests(unittest.TestCase):
    DIR = ROOT / "vendor" / "rfc4287"

    def test_schema_matches_the_hash_recorded_with_its_source(self):
        digest = hashlib.sha256((self.DIR / "atom.rnc").read_bytes()).hexdigest()
        self.assertIn(digest, (self.DIR / "README.md").read_text())

    def test_it_is_the_rfc_4287_grammar(self):
        text = (self.DIR / "atom.rnc").read_text()
        self.assertTrue(text.startswith("# -*- rnc -*-\n"))
        self.assertIn('namespace atom = "http://www.w3.org/2005/Atom"', text)
        self.assertIn("atomFeed =", text)
        self.assertNotIn("[Page ", text)

    def test_readme_names_the_source_and_the_licence_notice(self):
        readme = (self.DIR / "README.md").read_text()
        self.assertIn("https://www.rfc-editor.org/rfc/rfc4287.txt", readme)
        self.assertIn("BCP 78", readme)

    def test_the_check_script_no_longer_needs_the_network(self):
        src = (ROOT / ".github/scripts/validate_atom.py").read_text()
        self.assertNotIn("urllib", src)
        self.assertNotIn("rfc-editor.org", src)


if __name__ == "__main__":
    unittest.main()
