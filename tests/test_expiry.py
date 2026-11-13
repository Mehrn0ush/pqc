import json
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from pqc_tracker import expiry, issues, site, snapshot
from pqc_tracker.validate import ROOT, schema_errors, validate_data_dir
from tests.fixture_data import FIXTURE_DATA, load_fixture_data
from tests.helpers import FakeFetcher, claim, impl
from tests.test_failclosed import STDS, routes

API = "https://api.github.com"
EVIDENCE = "https://example.org/old-statement"
# statement 2026-01-01 -> first expired day 2027-01-02
PLANNED = claim(status="planned", statement_date="2026-01-01", evidence_url=EVIDENCE, note="Said so.")
BEFORE, ON, AFTER = date(2027, 1, 1), date(2027, 1, 2), date(2027, 3, 1)


def impls():
    return [impl(id="x", name="X", algs={"slhdsa": PLANNED})]


class EffectiveTests(unittest.TestCase):
    def test_before_expiry_the_cell_is_planned(self):
        got = expiry.effective(impls(), BEFORE)
        self.assertEqual(got[0]["algorithms"]["slhdsa"]["status"], "planned")

    def test_on_and_after_expiry_the_cell_is_no_statement_found(self):
        for today in (ON, AFTER):
            c = expiry.effective(impls(), today)[0]["algorithms"]["slhdsa"]
            self.assertEqual(c["status"], "no-statement-found")
            self.assertEqual(c["expired_planned"]["expired_on"], "2027-01-02")
            self.assertEqual(c["expired_planned"]["url"], EVIDENCE)

    def test_the_input_is_not_rewritten(self):
        src = impls()
        expiry.effective(src, AFTER)
        self.assertEqual(src[0]["algorithms"]["slhdsa"]["status"], "planned")


class EntryTests(unittest.TestCase):
    def test_no_entry_before_expiry_one_entry_dated_on_the_expiry_day_after(self):
        self.assertEqual(expiry.expiry_entries(impls(), BEFORE), [])
        for today in (ON, AFTER):
            (e,) = expiry.expiry_entries(impls(), today)
            self.assertEqual(
                (e["kind"], e["date"], e["detected_by"]), ("planned-expired", "2027-01-02", "machine")
            )
            self.assertEqual((e["from"], e["to"], e["url"]), ("planned", "no-statement-found", EVIDENCE))
        self.assertEqual(
            expiry.expiry_entries(impls(), ON)[0]["id"], expiry.expiry_entries(impls(), AFTER)[0]["id"]
        )
        self.assertEqual(
            schema_errors(
                "changelog",
                {"schema_version": "1.0.0", "entries": expiry.expiry_entries(impls(), ON)},
                ROOT / "schemas",
            ),
            [],
        )


class CollectRecordsExpiryTests(unittest.TestCase):
    def test_entry_is_added_once_and_dated_on_the_expiry_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            first = snapshot.run_collect(
                FakeFetcher(routes()), impls_with_release(), STDS, d, datetime(2027, 1, 1, 6, tzinfo=UTC)
            )
            self.assertEqual([e for e in first if e["kind"] == "planned-expired"], [])
            second = snapshot.run_collect(
                FakeFetcher(routes()), impls_with_release(), STDS, d, datetime(2027, 1, 20, 6, tzinfo=UTC)
            )
            (e,) = [e for e in second if e["kind"] == "planned-expired"]
            self.assertEqual(e["date"], "2027-01-02")
            third = snapshot.run_collect(
                FakeFetcher(routes()), impls_with_release(), STDS, d, datetime(2027, 2, 1, 6, tzinfo=UTC)
            )
            self.assertEqual([e for e in third if e["kind"] == "planned-expired"], [])
            log = json.loads((d / "changelog.json").read_text())["entries"]
            self.assertEqual([x["kind"] for x in log].count("planned-expired"), 1)


def impls_with_release():
    """The collector fixture project (id 'x') carrying a planned cell."""
    return [impl(id="x", name="X", algs={"slhdsa": PLANNED})]


class IssueTests(unittest.TestCase):
    def listing(self, existing):
        return FakeFetcher(
            {f"{API}/repos/o/r/issues?labels=review-needed&state=all&per_page=100&page=1": existing}
        )

    def test_nothing_far_from_expiry(self):
        self.assertEqual(issues.plan_expiry(impls(), [], date(2026, 6, 1)), [])

    def test_warning_issue_30_days_ahead_then_expired_issue_is_a_second_type(self):
        (warn,) = issues.plan_expiry(impls(), [], date(2026, 12, 3))
        self.assertIn("expires 2027-01-02", warn.title)
        self.assertIn("in 30 days", warn.body)
        (dead,) = issues.plan_expiry(impls(), [{"state": "open", "body": warn.body}], ON)
        self.assertIn("expired 2027-01-02", dead.title)
        self.assertNotEqual(warn.body.splitlines()[0], dead.body.splitlines()[0])
        self.assertIn(EVIDENCE, dead.body)

    def test_no_duplicates_even_when_the_earlier_issue_was_closed(self):
        (a,) = issues.plan_expiry(impls(), [], AFTER)
        for state in ("open", "closed"):
            self.assertEqual(issues.plan_expiry(impls(), [{"state": state, "body": a.body}], AFTER), [])

    def test_one_issue_per_cell(self):
        two = [impl(id="x", name="X", algs={"slhdsa": PLANNED, "mldsa": PLANNED})]
        self.assertEqual(len(issues.plan_expiry(two, [], AFTER)), 2)

    def test_a_restated_statement_gets_a_new_issue_later(self):
        (old,) = issues.plan_expiry(impls(), [], AFTER)
        newer = [
            impl(id="x", name="X", algs={"slhdsa": claim(status="planned", statement_date="2027-02-01")})
        ]
        (fresh,) = issues.plan_expiry(newer, [{"state": "closed", "body": old.body}], date(2028, 3, 1))
        self.assertNotEqual(fresh.body.splitlines()[0], old.body.splitlines()[0])

    def test_generic_planner_ignores_expiry_entries(self):
        (e,) = expiry.expiry_entries(impls(), AFTER)
        self.assertEqual(issues.plan([e], [], {"x": impls()[0]}), [])

    def test_apply_creates_one_issue_and_is_idempotent(self):
        f = self.listing([])
        acts = issues.apply(f, "o/r", [], impls(), AFTER)
        self.assertEqual(len(acts), 1)
        created = [b for m, u, b in f.calls if m == "POST" and u.endswith("/issues")]
        self.assertEqual(created[0]["labels"], ["review-needed"])
        f2 = FakeFetcher(
            {
                f"{API}/repos/o/r/labels/review-needed": {"name": "review-needed"},
                f"{API}/repos/o/r/issues?labels=review-needed&state=all&per_page=100&page=1": [
                    {"number": 4, "state": "open", "body": created[0]["body"]}
                ],
            }
        )
        self.assertEqual(issues.apply(f2, "o/r", [], impls(), AFTER), [])
        self.assertEqual([c for c in f2.calls if c[0] == "POST"], [])


class RenderingTests(unittest.TestCase):
    def build(self, today):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = load_fixture_data()
        ctx = site.Context(
            expiry.effective(impls(), today),
            d["standards"],
            d["snapshot"],
            d["status"],
            [],
            datetime(2027, 3, 1, tzinfo=UTC),
        )
        out = Path(tmp.name)
        site.build_site(ctx, out, ROOT / "schemas")
        return (
            (out / "index.html").read_text(),
            (out / "implementations/x/index.html").read_text(),
            json.loads((out / "data/latest.json").read_text()),
        )

    def test_before_expiry_planned_is_shown(self):
        home, page, _ = self.build(BEFORE)
        self.assertIn("Planned", home)
        self.assertNotIn("expired", home)

    def test_after_expiry_shows_no_statement_found_with_text_and_link(self):
        home, page, latest = self.build(AFTER)
        for html in (home, page):
            self.assertIn("previous 'planned' statement expired 2027-01-02", html)
            self.assertIn(f'href="{EVIDENCE}"', html)
            self.assertIn("No statement found", html)
        self.assertIn("History, not a current claim:", page)
        self.assertEqual(latest["implementations"][0]["algorithms"]["slhdsa"]["status"], "no-statement-found")


class BuildDoesNotFailTests(unittest.TestCase):
    def test_validation_with_an_expired_cell_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            import shutil

            data = Path(tmp) / "data"
            shutil.copytree(FIXTURE_DATA, data)
            text = (
                (data / "implementations.yaml")
                .read_text()
                .replace("statement_date: '2026-07-14'", "statement_date: '2020-01-01'")
            )
            self.assertNotEqual(text, (data / "implementations.yaml").read_text())
            (data / "implementations.yaml").write_text(text)
            d = validate_data_dir(data, today=date(2026, 11, 12))
            from pqc_tracker.validate import semantic_warnings

            self.assertTrue(
                any("expired on" in w for w in semantic_warnings(d["implementations"], date(2026, 11, 12)))
            )


if __name__ == "__main__":
    unittest.main()
