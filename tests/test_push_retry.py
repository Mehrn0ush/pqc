import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from pqc_tracker.validate import ROOT

SCRIPT = ROOT / ".github" / "scripts" / "push-with-retry.sh"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.org",
}


def git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, capture_output=True, text=True, check=check)


class PushWithRetryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.origin = root / "origin.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.a, self.b = root / "a", root / "b"
        git(root, "clone", "-q", str(self.origin), str(self.a))
        git(self.a, "checkout", "-q", "-b", "main")
        (self.a / "data").mkdir()
        (self.a / "data/x.json").write_text("{}\n")
        (self.a / "data/y.json").write_text("{}\n")
        git(self.a, "add", "-A")
        git(self.a, "commit", "-q", "-m", "init")
        git(self.a, "push", "-q", "origin", "main")
        git(root, "clone", "-q", str(self.origin), str(self.b))

    def run_script(self):
        return subprocess.run([str(SCRIPT), "main"], cwd=self.a, env=ENV, capture_output=True, text=True)

    def commit(self, repo, name, text, message):
        (repo / "data" / name).write_text(text)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", message)

    def origin_log(self):
        return git(self.origin, "log", "--format=%s", "main").stdout.split("\n")[:-1]

    def test_plain_push_works(self):
        self.commit(self.a, "x.json", '{"a": 1}\n', "collect")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.origin_log()[0], "collect")

    def test_concurrent_push_to_another_file_is_rebased_over(self):
        self.commit(self.a, "x.json", '{"a": 1}\n', "collect")
        self.commit(self.b, "y.json", '{"b": 1}\n', "someone else")
        git(self.b, "push", "-q", "origin", "main")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.origin_log()[:2], ["collect", "someone else"])

    def test_conflicting_change_fails_at_once_and_leaves_a_clean_tree(self):
        self.commit(self.a, "x.json", '{"a": 1}\n', "collect")
        self.commit(self.b, "x.json", '{"b": 1}\n', "someone else")
        git(self.b, "push", "-q", "origin", "main")
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(git(self.a, "status", "--porcelain").stdout, "")
        self.assertEqual(self.origin_log()[0], "someone else")

    def test_gives_up_after_three_rejected_pushes(self):
        counter = Path(self.origin.parent / "count")
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text(f'#!/bin/sh\necho x >> "{counter}"\nexit 1\n')
        hook.chmod(0o755)
        self.commit(self.a, "x.json", '{"a": 1}\n', "collect")
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(counter.read_text().split()), 3)
        self.assertIn("giving up after 3 attempts", r.stderr)

    def test_recovers_when_the_first_push_loses_a_race(self):
        """A reject on the first attempt, success on the second, with a new upstream commit in between."""
        counter = Path(self.origin.parent / "count")
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text(
            f'#!/bin/sh\nif [ ! -s "{counter}" ]; then echo x > "{counter}"; exit 1; fi\nexit 0\n'
        )
        hook.chmod(0o755)
        self.commit(self.a, "x.json", '{"a": 1}\n', "collect")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.origin_log()[0], "collect")

    def test_workflow_uses_the_script_for_both_pushes(self):
        text = (ROOT / ".github/workflows/collect.yml").read_text()
        self.assertEqual(text.count(".github/scripts/push-with-retry.sh main"), 2)
        self.assertNotIn("git push", text)


if __name__ == "__main__":
    unittest.main()
