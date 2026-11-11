import copy
import tempfile
import unittest
from datetime import date
from pathlib import Path

import yaml

from pqc_tracker.errors import ValidationError
from pqc_tracker.validate import ROOT, schema_errors, semantic_errors, validate_data_dir
from tests.helpers import impl, std

SCHEMAS = ROOT / "schemas"


class RealDataTests(unittest.TestCase):
    def test_repository_data_is_valid(self):
        d = validate_data_dir(ROOT / "data", today=date(2099, 1, 1))
        self.assertGreaterEqual(len(d["implementations"]), 12)

    def test_seed_scope_is_complete(self):
        d = validate_data_dir(ROOT / "data", today=date(2099, 1, 1))
        ids = {i["id"] for i in d["implementations"]}
        self.assertEqual(
            ids,
            {
                "openssl",
                "boringssl",
                "aws-lc",
                "wolfssl",
                "liboqs",
                "botan",
                "bouncycastle",
                "go",
                "openjdk",
                "rustls",
                "nss",
                "openssh",
            },
        )
        sids = {s["id"] for s in d["standards"]}
        for required in (
            "fips-203",
            "fips-204",
            "fips-205",
            "fips-206",
            "hqc",
            "nist-additional-signatures",
            "nist-ir-8547",
        ):
            self.assertIn(required, sids)
        groups = {s["group"] for s in d["standards"] if s["body"] == "IETF"}
        self.assertEqual(groups, {"tls", "lamps", "pquip"})

    def test_every_non_unverified_claim_has_evidence_and_date(self):
        d = validate_data_dir(ROOT / "data", today=date(2099, 1, 1))
        for i in d["implementations"]:
            for alg, c in i["algorithms"].items():
                if c["status"] != "unverified":
                    self.assertTrue(c["evidence_url"].startswith("https://"), (i["id"], alg))
                    self.assertTrue(c["verified_on"])


class SchemaTests(unittest.TestCase):
    def base(self):
        return [impl()]

    def test_supported_without_evidence_is_rejected(self):
        data = self.base()
        data[0]["algorithms"]["mlkem"] = {"status": "supported", "verified_on": "2026-11-11"}
        errs = schema_errors("implementations", data, SCHEMAS)
        self.assertTrue(any("evidence_url" in e for e in errs), errs)

    def test_supported_with_evidence_is_accepted(self):
        data = self.base()
        data[0]["algorithms"]["mlkem"] = {
            "status": "supported",
            "verified_on": "2026-11-11",
            "evidence_url": "https://example.org/e",
            "since_version": "1",
        }
        self.assertEqual(schema_errors("implementations", data, SCHEMAS), [])

    def test_unverified_cannot_claim_a_version(self):
        data = self.base()
        data[0]["algorithms"]["mlkem"]["since_version"] = "1.0"
        self.assertTrue(schema_errors("implementations", data, SCHEMAS))

    def test_http_evidence_is_rejected(self):
        data = self.base()
        data[0]["algorithms"]["mlkem"] = {
            "status": "supported",
            "verified_on": "2026-11-11",
            "evidence_url": "http://example.org",
        }
        self.assertTrue(schema_errors("implementations", data, SCHEMAS))

    def test_unknown_status_rejected(self):
        data = self.base()
        data[0]["algorithms"]["mlkem"]["status"] = "great"
        self.assertTrue(schema_errors("implementations", data, SCHEMAS))

    def test_missing_algorithm_rejected(self):
        data = self.base()
        del data[0]["algorithms"]["slhdsa"]
        self.assertTrue(schema_errors("implementations", data, SCHEMAS))

    def test_ietf_standard_needs_datatracker_name(self):
        self.assertTrue(schema_errors("standards", [std(body="IETF")], SCHEMAS))

    def test_bad_date_rejected(self):
        self.assertTrue(schema_errors("standards", [std(verified_on="11/11/2026")], SCHEMAS))

    def test_changelog_rejects_unknown_kind(self):
        bad = {
            "schema_version": "1.0.0",
            "entries": [
                {
                    "id": "a" * 16,
                    "date": "2026-01-01",
                    "kind": "rumour",
                    "subject_type": "standard",
                    "subject_id": "x",
                    "title": "t",
                    "detected_by": "machine",
                }
            ],
        }
        self.assertTrue(schema_errors("changelog", bad, SCHEMAS))

    def test_snapshot_rejects_extra_fields(self):
        bad = {
            "schema_version": "1.0.0",
            "collected_at": "2026-11-11T00:00:00Z",
            "releases": {},
            "drafts": {},
            "score": 1,
        }
        self.assertTrue(schema_errors("snapshot", bad, SCHEMAS))


class SemanticTests(unittest.TestCase):
    def test_duplicate_ids(self):
        errs = semantic_errors([impl(), impl()], [std(), std()], None, date(2026, 11, 12))
        self.assertEqual(len(errs), 2)

    def test_future_verified_on(self):
        i = impl()
        i["algorithms"]["mlkem"]["verified_on"] = "2030-01-01"
        self.assertTrue(semantic_errors([i], [std()], None, date(2026, 11, 12)))

    def test_rfc_published_needs_number(self):
        self.assertTrue(semantic_errors([impl()], [std(status="rfc-published")], None, date(2026, 11, 12)))

    def test_snapshot_lagging_the_yaml_is_not_an_error(self):
        snap = {"releases": {}, "drafts": {}}
        self.assertEqual(semantic_errors([impl()], [std()], snap, date(2026, 11, 12)), [])


class DirTests(unittest.TestCase):
    def test_validate_data_dir_reports_all_problems(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            bad = copy.deepcopy([impl()])
            bad[0]["algorithms"]["mlkem"] = {"status": "supported", "verified_on": "2026-11-11"}
            (d / "implementations.yaml").write_text(yaml.safe_dump(bad))
            (d / "standards.yaml").write_text(yaml.safe_dump([std(verified_on="nope")]))
            with self.assertRaises(ValidationError) as cm:
                validate_data_dir(d)
            self.assertIn("implementations", str(cm.exception))
            self.assertIn("standards", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
