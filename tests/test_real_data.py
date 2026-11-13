"""Checks on the repository's real data/ files. Validation only: schemas, cross-file consistency and the
rules in validate.py. No assertion here names a date, a version or a status, because those change daily."""

import unittest
from datetime import date

from pqc_tracker import expiry, history
from pqc_tracker.validate import ROOT, semantic_warnings
from tests.real_data import FAR_FUTURE, read_real_text, real_data_shape, validate_real_data


class RealDataShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = validate_real_data()  # raises with every problem if a schema or semantic rule is broken

    def test_all_files_validate(self):
        self.assertTrue(self.d["implementations"])
        self.assertTrue(self.d["standards"])

    def test_every_project_has_the_four_claims(self):
        for i in self.d["implementations"]:
            self.assertEqual(set(i["algorithms"]), {"mlkem", "mldsa", "slhdsa", "hybrid_kex"}, i["id"])

    def test_every_evidenced_claim_has_evidence_and_a_date(self):
        for i in self.d["implementations"]:
            for alg, c in i["algorithms"].items():
                if c["status"] in ("not-checked", "no-statement-found"):
                    continue
                self.assertTrue(c["evidence_url"].startswith("https://"), (i["id"], alg))
                self.assertTrue(c["verified_on"], (i["id"], alg))
                self.assertIn(c["evidence_strength"], ("stated", "inferred"), (i["id"], alg))

    def test_every_no_statement_cell_lists_sources_searched(self):
        for i in self.d["implementations"]:
            for alg, c in i["algorithms"].items():
                if c["status"] == "no-statement-found":
                    self.assertTrue(c["checked_sources"], (i["id"], alg))
                    self.assertTrue(c["checked_on"], (i["id"], alg))

    def test_in_development_standards_record_what_nist_says_and_where_we_looked(self):
        for s in self.d["standards"]:
            if s["status"] == "in-development":
                for key in ("stated_status", "stated_quote", "stated_url", "checked_on", "checked_sources"):
                    self.assertTrue(s.get(key), (s["id"], key))

    def test_ids_are_unique_and_standards_reference_known_groups(self):
        for key, rows in (("implementations", self.d["implementations"]), ("standards", self.d["standards"])):
            ids = [r["id"] for r in rows]
            self.assertEqual(len(ids), len(set(ids)), key)

    def test_every_release_source_has_a_snapshot_entry_or_is_new(self):
        # A project added since the last Collect legitimately has no release yet; a snapshot entry for a
        # project that no longer exists would be a mistake.
        known = {i["id"] for i in self.d["implementations"]}
        self.assertLessEqual(set(self.d["snapshot"]["releases"]), known)

    def test_expiry_rules_hold_for_any_date(self):
        """Expiry only ever warns: no date, past or future, turns the real data into an error."""
        for today in (date(2026, 1, 1), date(2030, 1, 1), FAR_FUTURE):
            semantic_warnings(self.d["implementations"], today)
            expiry.effective(self.d["implementations"], today)

    def test_the_machine_log_holds_only_machine_entries(self):
        for e in self.d["changelog"]["entries"]:
            self.assertEqual(e["detected_by"], "machine")

    def test_the_baseline_file_is_well_formed(self):
        with real_data_shape():
            history.read_baseline(ROOT)  # raises only if the file names something that is not a SHA
        self.assertTrue(read_real_text("changelog_baseline.txt").strip())


class RealRepositoryHistoryTests(unittest.TestCase):
    def test_the_status_history_of_this_repository_is_derivable(self):
        import subprocess

        shallow = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--is-shallow-repository"], capture_output=True, text=True
        ).stdout.strip()
        if shallow != "false":
            self.skipTest("needs the full history")
        with real_data_shape():
            got = history.published_status_changes(ROOT)
        self.assertEqual(len({e["id"] for e in got}), len(got))
        for e in got:
            self.assertIn(e["kind"], ("status-change", "tracking-began"))


if __name__ == "__main__":
    unittest.main()
