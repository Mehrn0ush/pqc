"""The guards that keep tests independent of live data and the wall clock."""

import os
import re
import unittest

from pqc_tracker import util
from pqc_tracker.validate import ROOT
from tests.fixture_data import FIXTURE_DATA
from tests.guard import RealDataAccess
from tests.real_data import real_data_shape

TESTS = ROOT / "tests"
SRC = ROOT / "src" / "pqc_tracker"
# The only files allowed to name the real data directory.
REAL_DATA_ALLOWED = {"guard.py", "real_data.py", "test_guard.py", "test_real_data.py"}
CLOCK = re.compile(r"\b(date\.today\(|datetime\.now\(|datetime\.utcnow\(|time\.time\(\))")


class RuntimeGuardTests(unittest.TestCase):
    def test_reading_real_data_is_refused(self):
        for read in (
            lambda: (ROOT / "data" / "implementations.yaml").read_text(),
            lambda: (ROOT / "data" / "snapshots" / "latest.json").read_bytes(),
            lambda: open(ROOT / "data" / "changelog.json"),
            lambda: util.load_json(ROOT / "data" / "collection-status.json"),
        ):
            with self.assertRaises(RealDataAccess):
                read()

    def test_the_named_helper_allows_it_and_only_inside_its_block(self):
        with real_data_shape():
            self.assertTrue((ROOT / "data" / "implementations.yaml").read_text())
        with self.assertRaises(RealDataAccess):
            (ROOT / "data" / "implementations.yaml").read_text()

    def test_fixtures_and_schemas_are_readable(self):
        self.assertTrue((FIXTURE_DATA / "implementations.yaml").read_text())
        self.assertTrue(next((ROOT / "schemas").glob("*.json")).read_text())

    def test_the_guard_message_says_what_to_do(self):
        with self.assertRaises(RealDataAccess) as cm:
            (ROOT / "data" / "standards.yaml").read_text()
        self.assertIn("tests/fixtures/data", str(cm.exception))
        self.assertIn("real_data_shape", str(cm.exception))


class ClockGuardTests(unittest.TestCase):
    def test_the_clock_is_injected_for_the_whole_run(self):
        self.assertTrue(os.environ.get("PQC_NOW"))
        self.assertEqual(util.utcnow().isoformat(), util.utcnow().isoformat())

    def test_pqc_now_sets_the_program_clock(self):
        old = os.environ["PQC_NOW"]
        try:
            os.environ["PQC_NOW"] = "2030-02-03T04:05:06Z"
            self.assertEqual(util.iso_z(util.utcnow()), "2030-02-03T04:05:06Z")
        finally:
            os.environ["PQC_NOW"] = old


class StaticScanTests(unittest.TestCase):
    def test_no_test_names_the_real_data_directory_outside_the_helpers(self):
        pattern = re.compile(r"""ROOT\s*/\s*["']data["']|validate_data_dir\(\s*ROOT\b|REAL_DATA\b""")
        for path in sorted(TESTS.glob("*.py")):
            if path.name in REAL_DATA_ALLOWED:
                continue
            self.assertIsNone(pattern.search(path.read_text()), f"{path.name} reads the real data/ directory")

    def test_no_test_reads_the_wall_clock(self):
        for path in sorted(TESTS.glob("*.py")):
            if path.name == "test_guard.py":
                continue
            self.assertIsNone(CLOCK.search(path.read_text()), f"{path.name} reads the wall clock")

    def test_the_program_reads_the_wall_clock_in_one_place(self):
        # util.utcnow() is the single source; smoke.py's time.time_ns() is only a cache-busting token.
        for path in sorted(SRC.glob("*.py")):
            if path.name in ("util.py", "smoke.py"):
                continue
            self.assertIsNone(CLOCK.search(path.read_text()), f"{path.name} reads the wall clock")


if __name__ == "__main__":
    unittest.main()
