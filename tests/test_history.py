"""Confirmed status changes are rebuilt from git history alone: no network, no live site."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from pqc_tracker import changelog as cl
from pqc_tracker import cli, history
from pqc_tracker.errors import ValidationError
from pqc_tracker.validate import ROOT
from tests.helpers import claim, impl, std


def git(repo: Path, *args: str, when: str | None = None) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.org",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.org",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(repo),
    }
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True)
    return out.stdout


class FixtureRepo:
    """A throwaway repository whose commits edit data/implementations.yaml and data/standards.yaml."""

    def __init__(self, root: Path):
        self.path = root
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
        (root / "data").mkdir()

    def commit(self, impls, stds, when, message="edit"):
        (self.path / "data/implementations.yaml").write_text(yaml.safe_dump(impls, sort_keys=False))
        (self.path / "data/standards.yaml").write_text(yaml.safe_dump(stds, sort_keys=False))
        git(self.path, "add", "-A")
        git(self.path, "commit", "-q", "-m", message, when=when)
        return git(self.path, "rev-parse", "HEAD").strip()


def with_status(impls, iid, alg, **kw):
    out = copy.deepcopy(impls)
    for i in out:
        if i["id"] == iid:
            i["algorithms"][alg] = kw if "status" in kw else claim(**kw)
    return out


class DeriveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = FixtureRepo(self.root / "repo")
        self.base = [impl(id="a", name="A"), impl(id="b", name="B")]
        self.stds = [std(id="s1", status="draft")]

    def build_history(self):
        r = self.repo
        r.commit(self.base, self.stds, "2026-01-10T12:00:00+00:00", "baseline")
        v2 = with_status(self.base, "a", "mlkem", evidence_url="https://example.org/a-mlkem")
        r.commit(v2, self.stds, "2026-02-01T12:00:00+00:00", "A ML-KEM supported")
        v3 = with_status(
            v2, "a", "mlkem", status="experimental", **{k: v for k, v in claim().items() if k != "status"}
        )
        v3 = v3 + [impl(id="c", name="C")]
        r.commit(
            v3,
            [std(id="s1", status="final"), std(id="s2")],
            "2026-03-05T09:30:00+00:00",
            "downgrade, add C, finalise s1",
        )
        return v3

    def test_rebuilds_the_full_changelog_from_history(self):
        self.build_history()
        got = history.derive_status_changes(self.repo.path)
        summary = [(e["date"], e["subject_id"], e.get("algorithm"), e.get("from"), e["to"]) for e in got]
        self.assertEqual(
            summary,
            [
                ("2026-02-01", "a", "mlkem", "not-checked", "supported"),
                ("2026-03-05", "a", "mlkem", "supported", "experimental"),
                ("2026-03-05", "c", None, None, "added"),
                ("2026-03-05", "s1", None, "draft", "final"),
                ("2026-03-05", "s2", None, None, "added"),
            ],
        )
        for e in got:
            self.assertEqual(
                (e["kind"], e["detected_by"], e["human_confirmed"]), ("status-change", "human", True)
            )
        self.assertEqual(got[0]["url"], "https://example.org/a-mlkem")

    def test_baseline_commit_produces_nothing(self):
        self.repo.commit(self.base, self.stds, "2026-01-10T12:00:00+00:00")
        self.assertEqual(history.derive_status_changes(self.repo.path), [])

    def test_fresh_clone_gives_identical_entries(self):
        self.build_history()
        clone = self.root / "clone"
        subprocess.run(["git", "clone", "-q", f"file://{self.repo.path}", str(clone)], check=True)
        self.assertEqual(history.derive_status_changes(self.repo.path), history.derive_status_changes(clone))

    def test_repeated_runs_are_identical(self):
        self.build_history()
        a, b = (history.derive_status_changes(self.repo.path) for _ in range(2))
        self.assertEqual(a, b)
        self.assertEqual(len({e["id"] for e in a}), len(a))

    def test_flip_flop_on_one_day_keeps_distinct_entries(self):
        r = self.repo
        r.commit(self.base, self.stds, "2026-01-10T12:00:00+00:00")
        up = with_status(self.base, "a", "mlkem")
        r.commit(up, self.stds, "2026-01-11T08:00:00+00:00")
        r.commit(self.base, self.stds, "2026-01-11T09:00:00+00:00")
        r.commit(up, self.stds, "2026-01-11T10:00:00+00:00")
        got = history.derive_status_changes(r.path)
        self.assertEqual(len(got), 3)
        self.assertEqual(len({e["id"] for e in got}), 3)

    def test_renamed_status_is_not_a_change(self):
        legacy = copy.deepcopy(self.base)
        for i in legacy:
            for c in i["algorithms"].values():
                c["status"] = "unverified"
        self.repo.commit(legacy, self.stds, "2026-01-10T12:00:00+00:00")
        self.repo.commit(self.base, self.stds, "2026-01-11T12:00:00+00:00")
        self.assertEqual(history.derive_status_changes(self.repo.path), [])

    def test_edits_that_keep_the_status_are_not_changes(self):
        r = self.repo
        r.commit(self.base, self.stds, "2026-01-10T12:00:00+00:00")
        edited = with_status(self.base, "a", "mlkem", status="not-checked", note="a note")
        r.commit(edited, self.stds, "2026-01-11T12:00:00+00:00")
        self.assertEqual(history.derive_status_changes(r.path), [])

    def test_merge_commit_counts_once_on_the_first_parent_line(self):
        r = self.repo
        r.commit(self.base, self.stds, "2026-01-10T12:00:00+00:00")
        git(r.path, "checkout", "-q", "-b", "topic")
        r.commit(with_status(self.base, "a", "mlkem"), self.stds, "2026-01-12T12:00:00+00:00")
        r.commit(with_status(self.base, "a", "mlkem", note="wording"), self.stds, "2026-01-13T12:00:00+00:00")
        git(r.path, "checkout", "-q", "main")
        git(r.path, "merge", "-q", "--no-ff", "-m", "merge topic", "topic", when="2026-01-20T12:00:00+00:00")
        got = history.derive_status_changes(r.path)
        self.assertEqual([(e["date"], e["to"]) for e in got], [("2026-01-20", "supported")])

    def test_shallow_clone_is_refused(self):
        self.build_history()
        shallow = self.root / "shallow"
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", f"file://{self.repo.path}", str(shallow)], check=True
        )
        with self.assertRaises(ValidationError):
            history.derive_status_changes(shallow)

    def test_not_a_repository_is_refused(self):
        with self.assertRaises(ValidationError):
            history.derive_status_changes(self.root)

    def test_history_without_both_files_is_refused(self):
        (self.repo.path / "data/implementations.yaml").write_text("[]")
        git(self.repo.path, "add", "-A")
        git(self.repo.path, "commit", "-q", "-m", "only one file")
        with self.assertRaises(ValidationError):
            history.derive_status_changes(self.repo.path)


class BuildUsesHistoryOnlyTests(unittest.TestCase):
    def test_build_reads_machine_log_plus_git_history_and_never_the_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = FixtureRepo(root / "repo")
            base = [impl(id="a", name="A")]
            repo.commit(base, [std()], "2026-01-10T12:00:00+00:00")
            repo.commit(with_status(base, "a", "mlkem"), [std()], "2026-02-01T12:00:00+00:00")
            out = root / "site"
            import socket

            def no_network(*a, **k):
                raise AssertionError("build must not use the network")

            real, socket.socket = socket.socket, no_network
            try:
                rc = cli.main(["build", "--out", str(out), "--repo", str(repo.path)])
            finally:
                socket.socket = real
            self.assertEqual(rc, 0)
            published = json.loads((out / "data/changelog.json").read_text())["entries"]
            human = [e for e in published if e["kind"] == "status-change"]
            self.assertEqual([(e["subject_id"], e["to"]) for e in human], [("a", "supported")])
            self.assertFalse((out / "data/statuses.json").exists())

    def test_machine_entries_in_the_repo_log_are_kept(self):
        machine = [
            {
                "id": "m1",
                "date": "2026-05-01",
                "kind": "release",
                "subject_type": "implementation",
                "subject_id": "a",
                "title": "A: new release 2",
                "detected_by": "machine",
            }
        ]
        human = [
            {**machine[0], "id": "h1", "kind": "status-change", "detected_by": "human", "date": "2026-06-01"}
        ]
        merged = cl.merge_for_publication(machine, human)
        self.assertEqual([e["id"] for e in merged], ["h1", "m1"])

    def test_status_change_entries_cannot_be_committed_to_the_machine_log(self):
        from pqc_tracker.validate import validate_data_dir

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            (data / "snapshots").mkdir(parents=True)
            for name in ("implementations.yaml", "standards.yaml"):
                (data / name).write_text((ROOT / "data" / name).read_text())
            (data / "changelog.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "entries": [
                            {
                                "id": "0123456789abcdef",
                                "date": "2026-01-01",
                                "kind": "status-change",
                                "subject_type": "implementation",
                                "subject_id": "openssl",
                                "title": "t",
                                "detected_by": "human",
                                "human_confirmed": True,
                            }
                        ],
                    }
                )
            )
            with self.assertRaises(ValidationError) as cm:
                validate_data_dir(data)
            self.assertIn("derived from git history", str(cm.exception))


class RealRepositoryTests(unittest.TestCase):
    def test_this_repository_history_is_derivable(self):
        shallow = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--is-shallow-repository"], capture_output=True, text=True
        ).stdout.strip()
        if shallow != "false":
            self.skipTest("needs the full history")
        got = history.derive_status_changes(ROOT)
        self.assertEqual(len({e["id"] for e in got}), len(got))
        for e in got:
            self.assertEqual(e["kind"], "status-change")


if __name__ == "__main__":
    unittest.main()
