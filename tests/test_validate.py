import copy
import tempfile
import unittest
from datetime import date
from pathlib import Path

import yaml

from pqc_tracker.errors import ValidationError
from pqc_tracker.validate import ROOT, schema_errors, semantic_errors, validate_data_dir
from tests.helpers import claim, impl, std

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

    def test_every_evidenced_claim_has_evidence_and_date(self):
        d = validate_data_dir(ROOT / "data", today=date(2099, 1, 1))
        for i in d["implementations"]:
            for alg, c in i["algorithms"].items():
                if c["status"] in ("not-checked", "no-statement-found"):
                    continue
                self.assertTrue(c["evidence_url"].startswith("https://"), (i["id"], alg))
                self.assertTrue(c["verified_on"])
                self.assertIn(c["evidence_strength"], ("stated", "inferred"))

    def test_every_no_statement_cell_lists_sources_searched(self):
        d = validate_data_dir(ROOT / "data", today=date(2099, 1, 1))
        for i in d["implementations"]:
            for alg, c in i["algorithms"].items():
                if c["status"] == "no-statement-found":
                    self.assertTrue(c["checked_sources"], (i["id"], alg))
                    self.assertTrue(c["checked_on"])


class NistStatementTests(unittest.TestCase):
    def test_in_development_needs_nist_wording_page_date_and_sources(self):
        self.assertTrue(schema_errors("standards", [std(status="in-development")], SCHEMAS))
        ok = std(
            status="in-development",
            stated_status="in development",
            stated_quote="q",
            stated_url="https://example.org/p",
            checked_on="2026-11-11",
            checked_sources=["https://example.org/a"],
            no_draft_found=True,
        )
        self.assertEqual(schema_errors("standards", [ok], SCHEMAS), [])

    def test_no_draft_found_only_for_in_development(self):
        self.assertTrue(schema_errors("standards", [std(status="final", no_draft_found=True)], SCHEMAS))

    def test_fips_206_and_hqc_record_what_nist_says_and_where_we_looked(self):
        d = validate_data_dir(ROOT / "data", today=date(2099, 1, 1))
        by = {s["id"]: s for s in d["standards"]}
        for sid in ("fips-206", "hqc"):
            s = by[sid]
            self.assertTrue(s["no_draft_found"], sid)
            self.assertGreaterEqual(len(s["checked_sources"]), 5, sid)
            self.assertTrue(s["stated_url"].startswith("https://csrc.nist.gov/"), sid)
            self.assertTrue(s["checked_on"])


class SchemaTests(unittest.TestCase):
    def base(self):
        return [impl()]

    def put(self, **kw):
        data = self.base()
        data[0]["algorithms"]["mlkem"] = claim(**kw)
        return schema_errors("implementations", data, SCHEMAS)

    def test_supported_without_evidence_is_rejected(self):
        data = self.base()
        data[0]["algorithms"]["mlkem"] = {
            "status": "supported",
            "since_version": "1",
            "verified_on": "2026-11-11",
        }
        errs = schema_errors("implementations", data, SCHEMAS)
        self.assertTrue(any("evidence_url" in e for e in errs), errs)

    def test_supported_with_evidence_is_accepted(self):
        self.assertEqual(self.put(), [])

    def test_not_checked_cannot_carry_evidence_or_version(self):
        for extra in ({"since_version": "1.0"}, {"evidence_url": "https://example.org/e"}):
            data = self.base()
            data[0]["algorithms"]["mlkem"].update(extra)
            self.assertTrue(schema_errors("implementations", data, SCHEMAS), extra)

    def test_no_statement_found_needs_date_and_sources(self):
        data = self.base()
        data[0]["algorithms"]["mlkem"] = {"status": "no-statement-found", "note": "n"}
        self.assertTrue(schema_errors("implementations", data, SCHEMAS))
        data[0]["algorithms"]["mlkem"] = {
            "status": "no-statement-found",
            "checked_on": "2026-11-11",
            "checked_sources": ["https://example.org/a"],
            "note": "n",
        }
        self.assertEqual(schema_errors("implementations", data, SCHEMAS), [])

    def test_inferred_needs_reason_and_stated_cannot_have_one(self):
        self.assertTrue(self.put(evidence_strength="inferred"))
        self.assertEqual(self.put(evidence_strength="inferred", strength_reason="bug title only"), [])
        self.assertTrue(self.put(strength_reason="why"))

    def test_hybrid_only_needs_scheme(self):
        self.assertTrue(self.put(scope="hybrid-only"))
        self.assertEqual(self.put(scope="hybrid-only", scheme="X25519MLKEM768"), [])
        self.assertTrue(self.put(scheme="X25519MLKEM768"))

    def test_null_version_needs_note(self):
        self.assertTrue(self.put(since_version=None))
        self.assertEqual(self.put(since_version=None, since_note="no versioned releases"), [])

    def test_evidence_type_is_a_closed_list(self):
        self.assertTrue(self.put(evidence_type="blog-post"))

    def test_not_supported_is_still_a_status(self):
        self.assertEqual(
            self.put(status="not-supported", since_version=None, scope=None, evidence_type="official-docs"),
            [],
        )

    def test_source_code_alone_never_earns_supported(self):
        errs = semantic_errors(
            [
                impl(
                    algs={
                        "mlkem": claim(
                            evidence_type="source-code",
                            evidence_strength="inferred",
                            strength_reason="header",
                        )
                    }
                )
            ],
            [],
            None,
            date(2026, 11, 12),
        )
        self.assertTrue(any("source code alone" in e for e in errs), errs)
        ok = claim(
            status="experimental",
            evidence_type="source-code",
            evidence_strength="inferred",
            strength_reason="header",
        )
        self.assertEqual(semantic_errors([impl(algs={"mlkem": ok})], [], None, date(2026, 11, 12)), [])

    def test_source_code_cannot_be_stated(self):
        bad = claim(status="experimental", evidence_type="source-code")
        errs = semantic_errors([impl(algs={"mlkem": bad})], [], None, date(2026, 11, 12))
        self.assertTrue(errs)

    def test_scope_required_except_for_hybrid_column(self):
        c = claim(scope=None)
        errs = semantic_errors([impl(algs={"mlkem": c})], [], None, date(2026, 11, 12))
        self.assertTrue(any("scope is required" in e for e in errs), errs)
        errs = semantic_errors([impl(algs={"hybrid_kex": claim()})], [], None, date(2026, 11, 12))
        self.assertTrue(any("does not apply" in e for e in errs), errs)

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
