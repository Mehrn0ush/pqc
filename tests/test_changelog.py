import unittest

from pqc_tracker import changelog as cl
from tests.helpers import claim, impl, std


def snap(tag="1.0", rev="05", state="active", iesg="IESG Evaluation", rfc=None):
    return {
        "schema_version": "1.0.0",
        "collected_at": "2026-11-11T00:00:00Z",
        "releases": {"x": {"tag": tag, "published_at": "2026-11-01", "url": f"https://example.org/{tag}"}},
        "drafts": {
            "draft-a": {
                "rev": rev,
                "state": state,
                "iesg_state": iesg,
                "rfc": rfc,
                "updated_at": "2026-11-02",
                "url": "https://datatracker.ietf.org/doc/draft-a/",
            }
        },
    }


class MachineDiffTests(unittest.TestCase):
    def diff(self, old, new):
        return cl.diff_snapshots(old, new, {"x": "X"}, {"draft-a": "a"}, "2026-11-12")

    def test_first_snapshot_is_a_baseline_not_a_burst(self):
        self.assertEqual(self.diff(None, snap()), [])

    def test_no_change_no_entries(self):
        self.assertEqual(self.diff(snap(), snap()), [])

    def test_new_release(self):
        (e,) = self.diff(snap("1.0"), snap("1.1"))
        self.assertEqual(
            (e["kind"], e["detected_by"], e["from"], e["to"]), ("release", "machine", "1.0", "1.1")
        )
        self.assertEqual(e["date"], "2026-11-01")
        self.assertNotIn("human_confirmed", e)

    def test_new_draft_revision(self):
        (e,) = self.diff(snap(rev="05"), snap(rev="06"))
        self.assertEqual((e["kind"], e["to"], e["subject_id"]), ("draft-revision", "06", "a"))

    def test_draft_becomes_rfc(self):
        (e,) = self.diff(snap(), snap(state="rfc", iesg="RFC Published", rfc="RFC 99"))
        self.assertEqual((e["kind"], e["to"]), ("draft-state", "RFC 99"))

    def test_published_rfcs_never_generate_entries(self):
        rfc = dict(state="rfc", iesg="RFC Published", rfc="RFC 99")
        self.assertEqual(self.diff(snap(**rfc), snap(**rfc)), [])
        # Datatracker keeps touching RFC records (revision, timestamps, IESG label): still nothing.
        self.assertEqual(self.diff(snap(rev="05", **rfc), snap(rev="06", **{**rfc, "iesg": "Published"})), [])

    def test_active_draft_revision_after_state_change_is_still_logged(self):
        kinds = {
            e["kind"]
            for e in self.diff(snap(rev="05", iesg="IESG Evaluation"), snap(rev="06", iesg="RFC Ed Queue"))
        }
        self.assertEqual(kinds, {"draft-revision", "draft-state"})

    def test_iesg_state_change(self):
        (e,) = self.diff(snap(iesg="IESG Evaluation"), snap(iesg="RFC Ed Queue"))
        self.assertEqual((e["kind"], e["from"], e["to"]), ("draft-state", "IESG Evaluation", "RFC Ed Queue"))

    def test_project_new_to_snapshot_is_baseline(self):
        new = snap()
        new["releases"]["y"] = {"tag": "9", "published_at": None, "url": "https://example.org/9"}
        self.assertEqual(self.diff(snap(), new), [])

    def test_missing_publish_date_falls_back_to_detection_date(self):
        old, new = snap("1.0"), snap("1.1")
        new["releases"]["x"]["published_at"] = None
        (e,) = self.diff(old, new)
        self.assertEqual(e["date"], "2026-11-12")

    def test_ids_are_deterministic(self):
        a = self.diff(snap("1.0"), snap("1.1"))
        b = self.diff(snap("1.0"), snap("1.1"))
        self.assertEqual(a[0]["id"], b[0]["id"])

    def test_machine_diff_never_mentions_status(self):
        for e in self.diff(snap("1.0"), snap("1.1", rev="06")):
            self.assertNotEqual(e["kind"], "status-change")


class AppendOnlyTests(unittest.TestCase):
    def test_append_skips_duplicates_and_keeps_existing(self):
        (e,) = cl.diff_snapshots(snap("1.0"), snap("1.1"), {"x": "X"}, {}, "2026-11-12")
        log = {"schema_version": "1.0.0", "entries": []}
        once = cl.append_entries(log, [e])
        twice = cl.append_entries(once, [e])
        self.assertEqual(once, twice)
        self.assertEqual(len(twice["entries"]), 1)

    def test_existing_entries_are_untouched(self):
        old = {
            "id": "0" * 16,
            "date": "2020-01-01",
            "kind": "release",
            "subject_type": "implementation",
            "subject_id": "x",
            "title": "old",
            "detected_by": "machine",
        }
        out = cl.append_entries({"schema_version": "1.0.0", "entries": [old]}, [])
        self.assertEqual(out["entries"], [old])


class StatusDiffTests(unittest.TestCase):
    def test_no_baseline_no_entries(self):
        self.assertEqual(cl.diff_statuses(None, [impl()], [std()], "2026-11-12"), [])

    def test_unchanged_statuses_no_entries(self):
        i, s = [impl()], [std()]
        self.assertEqual(cl.diff_statuses(cl.statuses_of(i, s), i, s, "2026-11-12"), [])

    def test_implementation_status_change_is_human_confirmed(self):
        before = [impl()]
        base = cl.statuses_of(before, [])
        after = [impl(algs={"mlkem": claim()})]
        (e,) = cl.diff_statuses(base, after, [], "2026-11-12")
        self.assertEqual(
            (e["kind"], e["algorithm"], e["from"], e["to"]),
            ("status-change", "mlkem", "not-checked", "supported"),
        )
        self.assertEqual((e["detected_by"], e["human_confirmed"]), ("human", True))
        self.assertEqual(e["url"], "https://example.org/e")

    def test_since_version_or_note_edits_are_not_status_changes(self):
        base = cl.statuses_of([impl()], [])
        after = [impl(algs={"mlkem": {"status": "not-checked", "note": "edited"}})]
        self.assertEqual(cl.diff_statuses(base, after, [], "2026-11-12"), [])

    def test_an_added_document_that_is_already_an_rfc_is_not_news(self):
        rfc = std(
            id="r", body="IETF", status="rfc-published", group="tls", datatracker_name="draft-r", rfc="RFC 1"
        )
        draft = std(id="d", body="IETF", status="wg-draft", group="tls", datatracker_name="draft-d")
        base = cl.statuses_of([], [])
        got = cl.diff_statuses(base, [], [rfc, draft], "2026-11-12", ref="abc")
        self.assertEqual([e["subject_id"] for e in got], ["d"])

    def test_a_draft_becoming_an_rfc_is_a_status_change(self):
        before = std(id="d", body="IETF", status="rfc-ed-queue", group="tls", datatracker_name="draft-d")
        after = {**before, "status": "rfc-published", "rfc": "RFC 1"}
        (e,) = cl.diff_statuses(cl.statuses_of([], [before]), [], [after], "2026-11-12")
        self.assertEqual((e["from"], e["to"]), ("rfc-ed-queue", "rfc-published"))

    def test_standard_status_change(self):
        base = cl.statuses_of([], [std(status="draft")])
        (e,) = cl.diff_statuses(base, [], [std(status="final")], "2026-11-12")
        self.assertEqual((e["subject_type"], e["from"], e["to"]), ("standard", "draft", "final"))

    def test_new_entries_are_logged_as_added(self):
        base = cl.statuses_of([impl()], [std()])
        out = cl.diff_statuses(base, [impl(), impl(id="y", name="Y")], [std(), std(id="t")], "2026-11-12")
        self.assertEqual(sorted(e["to"] for e in out), ["added", "added"])


class MergeTests(unittest.TestCase):
    def entry(self, id, date):
        return {
            "id": id * 16,
            "date": date,
            "kind": "release",
            "subject_type": "implementation",
            "subject_id": "x",
            "title": id,
            "detected_by": "machine",
        }

    def test_union_dedup_sorted_newest_first(self):
        a, b, c = self.entry("a", "2026-01-01"), self.entry("b", "2026-03-01"), self.entry("c", "2026-02-01")
        out = cl.merge_for_publication([a, b], [b, c], [])
        self.assertEqual([e["title"] for e in out], ["b", "c", "a"])

    def test_previously_published_entries_cannot_disappear(self):
        old = self.entry("a", "2026-01-01")
        out = cl.merge_for_publication([], [old], [])
        self.assertEqual(out, [old])


if __name__ == "__main__":
    unittest.main()
