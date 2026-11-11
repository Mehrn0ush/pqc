import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pqc_tracker import snapshot
from pqc_tracker.errors import CollectionError
from pqc_tracker.util import dumps_json
from tests.helpers import FakeFetcher, fixture, impl, std

API = "https://api.github.com"
NOW = datetime(2026, 11, 12, 6, 0, 0, tzinfo=UTC)


def routes(tag="openssl-4.1.0"):
    rel = fixture("github_release_openssl.json")
    rel["tag_name"] = tag
    return {
        f"{API}/repos/o/x/releases/latest": rel,
        "https://datatracker.ietf.org/doc/draft-ietf-tls-mlkem/doc.json": fixture(
            "datatracker_draft-ietf-tls-mlkem.json"
        ),
    }


IMPLS = [impl()]
STDS = [
    std(
        id="tls-mlkem",
        body="IETF",
        status="rfc-ed-queue",
        group="tls",
        datatracker_name="draft-ietf-tls-mlkem",
    )
]


class OfficialPageFailClosedTests(unittest.TestCase):
    """A changed or broken official release page fails the whole run and writes no snapshot."""

    def test_broken_official_page_keeps_last_good_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            url = "https://www.openssh.org/releasenotes.html"
            ssh = impl(id="openssh", name="OpenSSH", source={"type": "openssh_release_notes", "url": url})
            good = FakeFetcher({**routes(), url: fixture("openssh_releasenotes_excerpt.html")})
            snapshot.run_collect(good, IMPLS + [ssh], STDS, d, NOW)
            before = (d / "snapshots/latest.json").read_text()
            bad = FakeFetcher({**routes(), url: "<html>maintenance</html>"})
            with self.assertRaises(CollectionError):
                snapshot.run_collect(bad, IMPLS + [ssh], STDS, d, NOW)
            self.assertEqual((d / "snapshots/latest.json").read_text(), before)
            self.assertEqual(
                json.loads((d / "snapshots/latest.json").read_text())["releases"]["openssh"]["date_source"],
                "official",
            )


class FailClosedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def good_run(self, tag="openssl-4.1.0", now=NOW):
        return snapshot.run_collect(FakeFetcher(routes(tag)), IMPLS, STDS, self.dir, now)

    def test_first_run_writes_snapshot_status_and_empty_changelog(self):
        self.assertEqual(self.good_run(), [])
        snap = json.loads((self.dir / "snapshots/latest.json").read_text())
        self.assertEqual(snap["releases"]["x"]["tag"], "openssl-4.1.0")
        status = json.loads((self.dir / "collection-status.json").read_text())
        self.assertEqual(status["status"], "ok")
        self.assertEqual(json.loads((self.dir / "changelog.json").read_text())["entries"], [])

    def test_second_run_with_new_release_appends_machine_entry(self):
        self.good_run("openssl-4.1.0")
        entries = self.good_run("openssl-4.2.0", datetime(2026, 11, 13, tzinfo=UTC))
        self.assertEqual([e["kind"] for e in entries], ["release"])
        log = json.loads((self.dir / "changelog.json").read_text())
        self.assertEqual(len(log["entries"]), 1)

    def test_rerun_with_same_data_adds_nothing(self):
        self.good_run("openssl-4.1.0")
        self.good_run("openssl-4.2.0", datetime(2026, 11, 13, tzinfo=UTC))
        self.good_run("openssl-4.2.0", datetime(2026, 11, 14, tzinfo=UTC))
        self.assertEqual(len(json.loads((self.dir / "changelog.json").read_text())["entries"]), 1)

    def test_one_failing_source_keeps_last_good_snapshot(self):
        self.good_run()
        before_snap = (self.dir / "snapshots/latest.json").read_text()
        before_log = (self.dir / "changelog.json").read_text()
        bad = routes("openssl-9.9.9")
        del bad["https://datatracker.ietf.org/doc/draft-ietf-tls-mlkem/doc.json"]  # draft source down
        with self.assertRaises(CollectionError):
            snapshot.run_collect(FakeFetcher(bad), IMPLS, STDS, self.dir, datetime(2026, 11, 13, tzinfo=UTC))
        self.assertEqual((self.dir / "snapshots/latest.json").read_text(), before_snap)
        self.assertEqual((self.dir / "changelog.json").read_text(), before_log)
        status = json.loads((self.dir / "collection-status.json").read_text())
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["last_good_collected_at"], "2026-11-12T06:00:00Z")
        self.assertIn("draft-ietf-tls-mlkem", status["error"])

    def test_malformed_data_is_not_partially_published(self):
        self.good_run()
        before = (self.dir / "snapshots/latest.json").read_text()
        bad = routes("openssl-9.9.9")
        bad[f"{API}/repos/o/x/releases/latest"] = {"tag_name": "openssl-9.9.9"}  # release half-parsed
        with self.assertRaises(CollectionError):
            snapshot.run_collect(FakeFetcher(bad), IMPLS, STDS, self.dir, datetime(2026, 11, 13, tzinfo=UTC))
        self.assertEqual((self.dir / "snapshots/latest.json").read_text(), before)

    def test_failure_with_no_previous_snapshot_writes_no_snapshot(self):
        with self.assertRaises(CollectionError):
            snapshot.run_collect(FakeFetcher({}), IMPLS, STDS, self.dir, NOW)
        self.assertFalse((self.dir / "snapshots/latest.json").exists())
        status = json.loads((self.dir / "collection-status.json").read_text())
        self.assertIsNone(status["last_good_collected_at"])

    def test_all_failures_are_reported_together(self):
        with self.assertRaises(CollectionError) as cm:
            snapshot.run_collect(FakeFetcher({}), IMPLS, STDS, self.dir, NOW)
        self.assertIn("x:", str(cm.exception))
        self.assertIn("draft-ietf-tls-mlkem", str(cm.exception))

    def test_status_and_snapshot_dump_stable(self):
        self.good_run()
        text = (self.dir / "snapshots/latest.json").read_text()
        self.assertEqual(text, dumps_json(json.loads(text)))


if __name__ == "__main__":
    unittest.main()
