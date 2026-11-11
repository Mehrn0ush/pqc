import unittest

from pqc_tracker import linkcheck
from tests.helpers import impl, std


class LinkCheckTests(unittest.TestCase):
    def data(self):
        i = impl()
        i["algorithms"]["mlkem"] = {
            "status": "supported",
            "verified_on": "2026-11-11",
            "evidence_url": "https://example.org/ev",
            "since_version": "1",
        }
        return [i], [std()]

    def test_collects_evidence_homepage_and_source_urls(self):
        urls = linkcheck.urls_to_check(*self.data())
        self.assertEqual(
            set(urls), {"https://example.org/", "https://example.org/ev", "https://example.org/s"}
        )

    def test_404_is_an_error_403_is_a_warning(self):
        codes = {"https://example.org/ev": 404, "https://example.org/": 403, "https://example.org/s": 200}
        errors, warnings = linkcheck.check(*self.data(), status_of=codes.__getitem__)
        self.assertEqual(len(errors), 1)
        self.assertIn("mlkem", errors[0])
        self.assertEqual(len(warnings), 1)

    def test_connection_error_is_an_error(self):
        def boom(url):
            raise OSError("dns")

        errors, _ = linkcheck.check(*self.data(), status_of=boom)
        self.assertEqual(len(errors), 3)


if __name__ == "__main__":
    unittest.main()
