import unittest

from pqc_tracker import ietf, sources
from pqc_tracker.errors import CollectionError
from tests.helpers import FakeFetcher, fixture

API = "https://api.github.com"


class GithubReleaseTests(unittest.TestCase):
    def test_parses_recorded_release(self):
        f = FakeFetcher(
            {f"{API}/repos/openssl/openssl/releases/latest": fixture("github_release_openssl.json")}
        )
        got = sources.github_release(f, "openssl/openssl")
        self.assertEqual(set(got), {"tag", "published_at", "url"})
        self.assertRegex(got["published_at"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(got["url"].startswith("https://github.com/openssl/openssl/releases/tag/"))

    def test_missing_field_is_an_error(self):
        data = fixture("github_release_openssl.json")
        del data["published_at"]
        f = FakeFetcher({f"{API}/repos/o/x/releases/latest": data})
        with self.assertRaises(CollectionError):
            sources.github_release(f, "o/x")

    def test_wrong_type_is_an_error(self):
        f = FakeFetcher(
            {
                f"{API}/repos/o/x/releases/latest": {
                    "tag_name": 5,
                    "published_at": "2026-01-01",
                    "html_url": "https://x",
                }
            }
        )
        with self.assertRaises(CollectionError):
            sources.github_release(f, "o/x")

    def test_html_instead_of_json_shape(self):
        f = FakeFetcher({f"{API}/repos/o/x/releases/latest": "<html>rate limited</html>"})
        with self.assertRaises(CollectionError):
            sources.github_release(f, "o/x")


class GithubTagsTests(unittest.TestCase):
    def routes(self):
        return {
            f"{API}/repos/randombit/botan/git/matching-refs/tags/3.": fixture("github_tags_botan.json"),
            f"{API}/repos/randombit/botan/commits/3.14.1": fixture("github_commit_botan_3_14_1.json"),
        }

    def test_picks_highest_numeric_version_ignoring_non_matching(self):
        got = sources.github_tags(
            FakeFetcher(self.routes()), "randombit/botan", "3.", r"^(\d+)\.(\d+)\.(\d+)$"
        )
        self.assertEqual(got["tag"], "3.14.1")
        self.assertEqual(got["published_at"], "2026-11-06")

    def test_numeric_not_lexicographic(self):
        routes = self.routes()
        routes[f"{API}/repos/randombit/botan/git/matching-refs/tags/3."] = [
            {"ref": "refs/tags/3.9.0"},
            {"ref": "refs/tags/3.14.1"},
        ]
        got = sources.github_tags(FakeFetcher(routes), "randombit/botan", "3.", r"^(\d+)\.(\d+)\.(\d+)$")
        self.assertEqual(got["tag"], "3.14.1")

    def test_no_match_fails(self):
        routes = self.routes()
        routes[f"{API}/repos/randombit/botan/git/matching-refs/tags/3."] = [{"ref": "refs/tags/nightly"}]
        with self.assertRaises(CollectionError):
            sources.github_tags(FakeFetcher(routes), "randombit/botan", "3.", r"^(\d+)\.(\d+)\.(\d+)$")

    def test_malformed_ref_fails(self):
        routes = self.routes()
        routes[f"{API}/repos/randombit/botan/git/matching-refs/tags/3."] = [{"nope": 1}]
        with self.assertRaises(CollectionError):
            sources.github_tags(FakeFetcher(routes), "randombit/botan", "3.", r"^(\d+)\.(\d+)\.(\d+)$")

    def test_missing_commit_date_fails(self):
        routes = self.routes()
        routes[f"{API}/repos/randombit/botan/commits/3.14.1"] = {"commit": {}}
        with self.assertRaises(CollectionError):
            sources.github_tags(FakeFetcher(routes), "randombit/botan", "3.", r"^(\d+)\.(\d+)\.(\d+)$")


class NssTests(unittest.TestCase):
    URL = "https://firefox-source-docs.mozilla.org/security/nss/releases/index.html"

    def test_reads_latest_version_line(self):
        got = sources.nss_release_notes(FakeFetcher({self.URL: fixture("nss_index_snippet.html")}), self.URL)
        self.assertEqual(got["tag"], "NSS 3.133")
        self.assertIsNone(got["published_at"])
        self.assertTrue(got["url"].endswith("/nss_3_133.html"))

    def test_page_without_the_line_fails(self):
        with self.assertRaises(CollectionError):
            sources.nss_release_notes(FakeFetcher({self.URL: "<html>redesigned</html>"}), self.URL)


class IetfTests(unittest.TestCase):
    def fetch(self, name):
        return FakeFetcher(
            {f"https://datatracker.ietf.org/doc/{name}/doc.json": fixture(f"datatracker_{name}.json")}
        )

    def test_published_rfc(self):
        n = "draft-ietf-tls-ecdhe-mlkem"
        got = ietf.collect_draft(self.fetch(n), n)
        self.assertEqual(got["state"], "rfc")
        self.assertEqual(got["rfc"], "RFC 10024")
        self.assertEqual(got["url"], f"https://datatracker.ietf.org/doc/{n}/")

    def test_active_draft_in_rfc_editor_queue(self):
        n = "draft-ietf-tls-mlkem"
        got = ietf.collect_draft(self.fetch(n), n)
        self.assertEqual((got["state"], got["rfc"], got["iesg_state"]), ("active", None, "RFC Ed Queue"))

    def test_unexpected_document_name(self):
        data = fixture("datatracker_draft-ietf-tls-mlkem.json")
        data["name"] = "draft-other"
        f = FakeFetcher({"https://datatracker.ietf.org/doc/draft-ietf-tls-mlkem/doc.json": data})
        with self.assertRaises(CollectionError):
            ietf.collect_draft(f, "draft-ietf-tls-mlkem")

    def test_unknown_state_fails(self):
        data = fixture("datatracker_draft-ietf-tls-mlkem.json")
        data["state"] = "Mystery"
        f = FakeFetcher({"https://datatracker.ietf.org/doc/draft-ietf-tls-mlkem/doc.json": data})
        with self.assertRaises(CollectionError):
            ietf.collect_draft(f, "draft-ietf-tls-mlkem")

    def test_rfc_state_without_number_fails(self):
        data = fixture("datatracker_draft-ietf-tls-ecdhe-mlkem.json")
        data["rev_history"] = [{"name": "draft-ietf-tls-ecdhe-mlkem"}]
        f = FakeFetcher({"https://datatracker.ietf.org/doc/draft-ietf-tls-ecdhe-mlkem/doc.json": data})
        with self.assertRaises(CollectionError):
            ietf.collect_draft(f, "draft-ietf-tls-ecdhe-mlkem")


if __name__ == "__main__":
    unittest.main()
