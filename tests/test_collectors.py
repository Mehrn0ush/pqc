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
        self.assertEqual(set(got), {"tag", "published_at", "date_source", "url"})
        self.assertEqual(got["date_source"], "official")
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
    PAGE = "https://firefox-source-docs.mozilla.org/security/nss/releases/nss_3_133.html"

    def fetcher(self, **over):
        routes = {self.URL: fixture("nss_index_snippet.html"), self.PAGE: fixture("nss_3_133_excerpt.html")}
        routes.update(over)
        return FakeFetcher(routes)

    def test_reads_latest_version_and_official_date(self):
        got = sources.nss_release_notes(self.fetcher(), self.URL)
        self.assertEqual(got["tag"], "NSS 3.133")
        self.assertEqual(got["published_at"], "2026-11-04")
        self.assertEqual(got["date_source"], "official")
        self.assertEqual(got["url"], self.PAGE)

    def test_page_without_the_line_fails(self):
        with self.assertRaises(CollectionError):
            sources.nss_release_notes(FakeFetcher({self.URL: "<html>redesigned</html>"}), self.URL)

    def test_release_page_without_a_date_fails_rather_than_guessing(self):
        with self.assertRaises(CollectionError):
            sources.nss_release_notes(self.fetcher(**{self.PAGE: "<p>NSS 3.133 notes</p>"}), self.URL)

    def test_release_page_for_another_version_fails(self):
        wrong = fixture("nss_3_133_excerpt.html").replace("(NSS) 3.133 was", "(NSS) 3.132 was")
        with self.assertRaises(CollectionError):
            sources.nss_release_notes(self.fetcher(**{self.PAGE: wrong}), self.URL)


class OfficialDatePageTests(unittest.TestCase):
    """Go, Botan, OpenSSH and Bouncy Castle: version and date come from the project's own release page."""

    def run_source(self, fn, url, name):
        return fn(FakeFetcher({url: fixture(name)}), url)

    def test_go_takes_highest_release_and_its_official_date(self):
        url = "https://go.dev/doc/devel/release"
        got = self.run_source(sources.go_release_history, url, "go_release_history_excerpt.html")
        self.assertEqual(
            (got["tag"], got["published_at"], got["date_source"]), ("go1.27.4", "2026-11-10", "official")
        )
        self.assertEqual(got["url"], f"{url}#go1.27.4")

    def test_botan_takes_dated_versions_only(self):
        url = "https://botan.randombit.net/news.html"
        got = self.run_source(sources.botan_news, url, "botan_news_excerpt.html")
        self.assertEqual(
            (got["tag"], got["published_at"], got["date_source"]), ("3.14.1", "2026-11-06", "official")
        )

    def test_openssh_date_is_the_announced_date_not_the_tag_commit(self):
        url = "https://www.openssh.org/releasenotes.html"
        got = self.run_source(sources.openssh_release_notes, url, "openssh_releasenotes_excerpt.html")
        self.assertEqual(got["tag"], "V_10_6_P2")
        self.assertEqual(got["published_at"], "2026-11-05")
        self.assertEqual(got["date_source"], "official")
        self.assertEqual(got["url"], "https://www.openssh.org/txt/release-10.6p2")

    def test_bouncy_castle_skips_unreleased_tbd_entry(self):
        url = "https://raw.githubusercontent.com/bcgit/bc-java/main/docs/releasenotes.md"
        got = self.run_source(sources.bc_release_notes, url, "bc_releasenotes_excerpt.md")
        self.assertEqual(
            (got["tag"], got["published_at"], got["date_source"]), ("r1rv86", "2026-09-11", "official")
        )

    def test_bouncy_castle_date_formats(self):
        for raw, want in (
            ("2026, 11th September.", "2026-09-11"),
            ("2026, July 12th", "2026-07-12"),
            ("2024, 30th October.", "2024-10-30"),
            ("2025, November 27th.", "2025-11-27"),
        ):
            self.assertEqual(sources._bc_date(raw, "t"), want)
        self.assertIsNone(sources._bc_date("2026, TBD", "t"))
        with self.assertRaises(CollectionError):
            sources._bc_date("sometime", "t")

    def test_pages_that_changed_shape_fail_closed(self):
        for fn, url in (
            (sources.go_release_history, "https://go.dev/doc/devel/release"),
            (sources.botan_news, "https://botan.randombit.net/news.html"),
            (sources.openssh_release_notes, "https://www.openssh.org/releasenotes.html"),
            (
                sources.bc_release_notes,
                "https://raw.githubusercontent.com/bcgit/bc-java/main/docs/releasenotes.md",
            ),
        ):
            with self.assertRaises(CollectionError, msg=url):
                fn(FakeFetcher({url: "<html>new design, no versions</html>"}), url)

    def test_impossible_date_fails(self):
        url = "https://botan.randombit.net/news.html"
        with self.assertRaises(CollectionError):
            sources.botan_news(FakeFetcher({url: "Version 3.14.1, 2026-13-45"}), url)

    def test_fetch_error_propagates(self):
        url = "https://go.dev/doc/devel/release"
        with self.assertRaises(CollectionError):
            sources.go_release_history(FakeFetcher({url: CollectionError("HTTP 503")}), url)

    def test_collect_release_dispatches_new_types(self):
        url = "https://botan.randombit.net/news.html"
        impl = {"id": "botan", "release_source": {"type": "botan_news", "url": url}}
        got = sources.collect_release(FakeFetcher({url: fixture("botan_news_excerpt.html")}), impl)
        self.assertEqual(got["tag"], "3.14.1")


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
