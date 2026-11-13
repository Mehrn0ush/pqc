import unittest
from datetime import UTC, datetime, timedelta

from pqc_tracker import watchdog
from pqc_tracker.errors import CollectionError
from pqc_tracker.watchdog import Alert, DataCommit, Live
from tests.helpers import FakeFetcher

API = "https://api.github.com"
REPO = "o/r"
NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
LIVE_SHA = "a" * 40
DATA_SHA = "b" * 40


def hours_ago(h):
    return NOW - timedelta(hours=h)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def live_built(hours):
    return Live({"commit": LIVE_SHA, "built_at": iso(hours_ago(hours)), "schema_version": "1.0.0"}, None)


def data_commit(hours, has=True):
    return DataCommit(DATA_SHA, hours_ago(hours), has)


class EvaluateTests(unittest.TestCase):
    def test_healthy(self):
        self.assertEqual(watchdog.evaluate(NOW, live_built(10), data_commit(3)), [])

    def test_build_age_boundary_is_48_hours(self):
        self.assertEqual(watchdog.evaluate(NOW, live_built(47), None), [])
        self.assertEqual(watchdog.evaluate(NOW, live_built(48), None), [])
        (a,) = watchdog.evaluate(NOW, live_built(49), None)
        self.assertEqual(a.code, "build-old")
        self.assertIn("49 hours old", a.message)

    def test_behind_main_boundary_is_6_hours(self):
        self.assertEqual(watchdog.evaluate(NOW, live_built(1), data_commit(5, has=False)), [])
        self.assertEqual(watchdog.evaluate(NOW, live_built(1), data_commit(6, has=False)), [])
        (a,) = watchdog.evaluate(NOW, live_built(1), data_commit(7, has=False))
        self.assertEqual(a.code, "behind-main")
        self.assertIn("bbbbbbb", a.message)
        self.assertIn("aaaaaaa", a.message)

    def test_a_data_commit_the_live_site_has_is_never_behind(self):
        self.assertEqual(watchdog.evaluate(NOW, live_built(1), data_commit(30, has=True)), [])

    def test_unknown_comparison_does_not_alert(self):
        self.assertEqual(watchdog.evaluate(NOW, live_built(1), data_commit(30, has=None)), [])

    def test_both_conditions_can_hold_at_once(self):
        codes = [a.code for a in watchdog.evaluate(NOW, live_built(60), data_commit(60, has=False))]
        self.assertEqual(codes, ["build-old", "behind-main"])

    def test_three_failed_fetches_alert_and_stop_further_checks(self):
        live = Live(None, "3 fetches in a row failed; last error: OSError: reset")
        (a,) = watchdog.evaluate(NOW, live, data_commit(99, has=False))
        self.assertEqual(a.code, "fetch-failed")

    def test_a_failed_run_alerts_immediately_with_its_link(self):
        run = {"name": "Collect", "conclusion": "failure", "url": "https://github.com/o/r/actions/runs/9"}
        (a,) = watchdog.evaluate(NOW, live_built(1), data_commit(1), failed_run=run)
        self.assertEqual(a.code, "run-failed")
        self.assertIn("https://github.com/o/r/actions/runs/9", a.message)
        self.assertIn("Collect", a.message)


class FetchLiveTests(unittest.TestCase):
    def fake(self, failures):
        calls = []

        def fetch(url):
            calls.append(url)
            if len(calls) <= failures:
                raise OSError("connection reset")
            return {"commit": LIVE_SHA, "built_at": "2026-11-13T00:00:00Z"} if "build.json" in url else {}

        return fetch, calls

    def test_first_try(self):
        fetch, calls = self.fake(0)
        live = watchdog.fetch_live("https://x", fetch=fetch, sleep=lambda s: None)
        self.assertIsNone(live.error)
        self.assertTrue(all("?cb=" in c for c in calls))

    def test_recovers_on_the_third_attempt(self):
        fetch, _ = self.fake(2)
        slept = []
        live = watchdog.fetch_live("https://x", fetch=fetch, sleep=slept.append, interval=30)
        self.assertIsNone(live.error)
        self.assertEqual(slept, [30, 30])

    def test_three_failures_in_a_row_is_an_error(self):
        fetch, calls = self.fake(99)
        live = watchdog.fetch_live("https://x", fetch=fetch, sleep=lambda s: None)
        self.assertIn("3 fetches in a row failed", live.error)
        self.assertEqual(len(calls), 3)

    def test_a_malformed_build_json_counts_as_a_failure(self):
        live = watchdog.fetch_live("https://x", fetch=lambda url: {"nope": 1}, sleep=lambda s: None)
        self.assertIn("not in the expected shape", live.error)


ALERT = [Alert("build-old", "old")]
OPEN = {"number": 7, "created_at": iso(hours_ago(30)), "state": "open"}


class PlanIssueTests(unittest.TestCase):
    def plan(self, alerts, issue=None, comments=(), allow_close=True):
        return watchdog.plan_issue(NOW, alerts, issue, list(comments), allow_close, "owner")

    def test_alert_with_no_open_issue_creates_one(self):
        p = self.plan(ALERT)
        self.assertEqual(p.action, "create")
        self.assertIn("build-old", p.body)
        self.assertIn("operations.md", p.body)

    def test_never_a_second_issue_while_one_is_open(self):
        for hours in (1, 23, 25, 100):
            issue = {**OPEN, "created_at": iso(hours_ago(hours))}
            self.assertNotEqual(self.plan(ALERT, issue).action, "create")

    def test_comment_at_most_once_a_day(self):
        young = {**OPEN, "created_at": iso(hours_ago(23))}
        self.assertEqual(self.plan(ALERT, young).action, "none")
        old = {**OPEN, "created_at": iso(hours_ago(24))}
        p = self.plan(ALERT, old)
        self.assertEqual((p.action, p.issue_number), ("comment", 7))

    def test_the_daily_clock_restarts_at_the_last_watchdog_comment_only(self):
        mine = {"body": watchdog.COMMENT_MARKER + " x", "created_at": iso(hours_ago(5))}
        human = {"body": "looking into it", "created_at": iso(hours_ago(1))}
        self.assertEqual(self.plan(ALERT, OPEN, [mine]).action, "none")
        self.assertEqual(self.plan(ALERT, OPEN, [human]).action, "comment")
        old_mine = {"body": watchdog.COMMENT_MARKER, "created_at": iso(hours_ago(25))}
        self.assertEqual(self.plan(ALERT, OPEN, [old_mine, human]).action, "comment")

    def test_closes_with_a_comment_when_healthy(self):
        p = self.plan([], OPEN)
        self.assertEqual((p.action, p.issue_number), ("close", 7))
        self.assertIn("Recovered", p.body)

    def test_the_failed_run_trigger_never_closes(self):
        self.assertEqual(self.plan([], OPEN, allow_close=False).action, "none")

    def test_healthy_and_nothing_open_does_nothing(self):
        self.assertEqual(self.plan([]).action, "none")


def routes(live_status="ahead", issues=(), comments=()):
    return {
        f"{API}/repos/{REPO}/commits?sha=main&path=data&per_page=1": [
            {"sha": DATA_SHA, "commit": {"committer": {"date": iso(hours_ago(8))}}}
        ],
        f"{API}/repos/{REPO}/compare/{DATA_SHA}...{LIVE_SHA}": {"status": live_status},
        f"{API}/repos/{REPO}/issues?labels=site-stale&state=open&per_page=30": list(issues),
        f"{API}/repos/{REPO}/issues/7/comments?per_page=100": list(comments),
        f"{API}/repos/{REPO}/labels/site-stale": {"name": "site-stale"},
    }


def live_fetch(hours):
    built = iso(hours_ago(hours))

    def fetch(url):
        if "build.json" in url:
            return {"commit": LIVE_SHA, "built_at": built, "schema_version": "1.0.0"}
        return {"implementations": []}

    return fetch


class RunTests(unittest.TestCase):
    def go(self, fetcher, hours=2, **kw):
        return watchdog.run(
            REPO,
            "https://live",
            "owner",
            NOW,
            fetcher,
            fetch=live_fetch(hours),
            sleep=lambda s: None,
            log=lambda m: None,
            **kw,
        )

    def posts(self, f):
        return [(m, u.split(f"/repos/{REPO}")[1], b) for m, u, b in f.calls if m != "GET"]

    def test_healthy_site_no_issue_no_writes(self):
        f = FakeFetcher(routes())
        alerts, plan = self.go(f)
        self.assertEqual((alerts, plan.action), ([], "none"))
        self.assertEqual(self.posts(f), [])

    def test_stale_site_opens_one_issue_labelled_and_assigned_to_the_owner(self):
        f = FakeFetcher(routes(live_status="behind"))
        alerts, plan = self.go(f)
        self.assertEqual([a.code for a in alerts], ["behind-main"])
        ((m, path, body),) = self.posts(f)
        self.assertEqual((m, path), ("POST", "/issues"))
        self.assertEqual(body["labels"], ["site-stale"])
        self.assertEqual(body["assignees"], ["owner"])

    def test_old_build_with_an_open_issue_comments_once_a_day(self):
        issue = {"number": 7, "created_at": iso(hours_ago(40)), "state": "open"}
        f = FakeFetcher(routes(issues=[issue]))
        alerts, plan = self.go(f, hours=60)
        self.assertEqual(plan.action, "comment")
        self.assertEqual([p[:2] for p in self.posts(f)], [("POST", "/issues/7/comments")])

    def test_recovery_comments_then_closes(self):
        issue = {"number": 7, "created_at": iso(hours_ago(40)), "state": "open"}
        f = FakeFetcher(routes(issues=[issue]))
        _, plan = self.go(f)
        self.assertEqual(plan.action, "close")
        self.assertEqual(
            [p[:2] for p in self.posts(f)], [("POST", "/issues/7/comments"), ("PATCH", "/issues/7")]
        )
        self.assertEqual(self.posts(f)[1][2], {"state": "closed"})

    def test_failed_run_trigger_raises_even_when_the_site_looks_fine_and_does_not_close(self):
        run = {"name": "Publish", "conclusion": "failure", "url": "https://github.com/o/r/actions/runs/5"}
        f = FakeFetcher(routes())
        alerts, plan = self.go(f, failed_run=run)
        self.assertEqual([a.code for a in alerts], ["run-failed"])
        self.assertEqual(plan.action, "create")
        issue = {"number": 7, "created_at": iso(hours_ago(2)), "state": "open"}
        f2 = FakeFetcher(routes(issues=[issue]))
        _, plan2 = self.go(f2, failed_run=run)
        self.assertEqual(plan2.action, "none")  # within a day of the open issue: no second issue, no spam

    def test_dry_run_writes_nothing(self):
        f = FakeFetcher(routes(live_status="behind"))
        _, plan = self.go(f, dry_run=True)
        self.assertEqual(plan.action, "create")
        self.assertEqual(self.posts(f), [])

    def test_unreachable_site_after_three_tries_opens_an_issue(self):
        def dead(url):
            raise OSError("down")

        f = FakeFetcher(routes())
        alerts, plan = watchdog.run(
            REPO, "https://live", "owner", NOW, f, fetch=dead, sleep=lambda s: None, log=lambda m: None
        )
        self.assertEqual([a.code for a in alerts], ["fetch-failed"])
        self.assertEqual(plan.action, "create")

    def test_github_not_answering_the_compare_does_not_raise_a_false_alarm(self):
        r = routes()
        del r[f"{API}/repos/{REPO}/compare/{DATA_SHA}...{LIVE_SHA}"]
        alerts, plan = self.go(FakeFetcher(r))
        self.assertEqual((alerts, plan.action), ([], "none"))

    def test_missing_label_is_created_before_the_issue(self):
        r = routes(live_status="behind")
        del r[f"{API}/repos/{REPO}/labels/site-stale"]
        f = FakeFetcher(r)
        self.go(f)
        self.assertEqual([p[1] for p in self.posts(f)], ["/labels", "/issues"])


class AuthorisedErrorTests(unittest.TestCase):
    def test_collection_error_type_is_what_the_fetcher_raises(self):
        self.assertTrue(issubclass(CollectionError, Exception))


if __name__ == "__main__":
    unittest.main()
