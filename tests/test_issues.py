import unittest

from pqc_tracker import issues
from tests.helpers import FakeFetcher, impl

API = "https://api.github.com"


def release_entry(tag, id_="a" * 16, subject="x"):
    return {
        "id": id_,
        "date": "2026-11-01",
        "kind": "release",
        "subject_type": "implementation",
        "subject_id": subject,
        "title": f"X: new release {tag}",
        "detected_by": "machine",
        "url": f"https://example.org/{tag}",
    }


class PlanTests(unittest.TestCase):
    IMPLS = {"x": impl()}

    def test_new_release_opens_one_issue_with_link_and_label_title(self):
        (a,) = issues.plan([release_entry("1.1")], [], self.IMPLS)
        self.assertEqual(a.kind, "create")
        self.assertTrue(a.title.startswith("review-needed:"))
        self.assertIn("https://example.org/1.1", a.body)
        self.assertIn("does not change any status", a.body)

    def test_same_entry_is_not_reported_twice_even_if_issue_closed(self):
        first = issues.plan([release_entry("1.1")], [], self.IMPLS)[0]
        existing = [{"number": 7, "state": "closed", "body": first.body}]
        self.assertEqual(issues.plan([release_entry("1.1")], existing, self.IMPLS), [])

    def test_open_issue_for_same_project_gets_a_comment_not_a_duplicate(self):
        first = issues.plan([release_entry("1.1", "a" * 16)], [], self.IMPLS)[0]
        existing = [{"number": 7, "state": "open", "body": first.body}]
        (a,) = issues.plan([release_entry("1.2", "b" * 16)], existing, self.IMPLS)
        self.assertEqual((a.kind, a.issue_number), ("comment", 7))

    def test_closed_issue_for_project_allows_a_new_issue(self):
        first = issues.plan([release_entry("1.1", "a" * 16)], [], self.IMPLS)[0]
        existing = [{"number": 7, "state": "closed", "body": first.body}]
        (a,) = issues.plan([release_entry("1.2", "b" * 16)], existing, self.IMPLS)
        self.assertEqual(a.kind, "create")

    def test_two_changes_same_run_one_issue_plus_comment(self):
        out = issues.plan([release_entry("1.1", "a" * 16), release_entry("1.2", "b" * 16)], [], self.IMPLS)
        self.assertEqual([a.kind for a in out], ["create", "comment"])

    def test_different_projects_get_separate_issues(self):
        out = issues.plan(
            [release_entry("1", "a" * 16, "x"), release_entry("1", "b" * 16, "y")], [], self.IMPLS
        )
        self.assertEqual([a.kind for a in out], ["create", "create"])

    def test_human_status_changes_open_no_issue(self):
        e = release_entry("1.1")
        e["kind"] = "status-change"
        self.assertEqual(issues.plan([e], [], self.IMPLS), [])

    def test_body_lists_statuses_but_does_not_change_them(self):
        (a,) = issues.plan([release_entry("1.1")], [], self.IMPLS)
        self.assertIn("ML-KEM: Not checked", a.body)


class ApplyTests(unittest.TestCase):
    def test_apply_creates_label_then_issue_with_label(self):
        repo = "o/r"
        # No route for the label GET: the fake raises, exactly like a real 404.
        f = FakeFetcher({f"{API}/repos/{repo}/issues?labels=review-needed&state=all&per_page=100&page=1": []})
        actions = issues.apply(f, repo, [release_entry("1.1")], [impl()])
        self.assertEqual(len(actions), 1)
        posts = [(u.split("/repos/o/r")[1], b) for m, u, b in f.calls if m == "POST"]
        self.assertEqual([p[0] for p in posts], ["/labels", "/issues"])
        self.assertEqual(posts[1][1]["labels"], ["review-needed"])

    def test_apply_is_idempotent_across_runs(self):
        repo = "o/r"
        first = issues.plan([release_entry("1.1")], [], {"x": impl()})[0]
        listing = [{"number": 3, "state": "open", "body": first.body}]
        f = FakeFetcher(
            {
                f"{API}/repos/{repo}/labels/review-needed": {"name": "review-needed"},
                f"{API}/repos/{repo}/issues?labels=review-needed&state=all&per_page=100&page=1": listing,
            }
        )
        self.assertEqual(issues.apply(f, repo, [release_entry("1.1")], [impl()]), [])
        self.assertEqual([c for c in f.calls if c[0] == "POST"], [])


if __name__ == "__main__":
    unittest.main()
