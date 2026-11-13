import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from pqc_tracker.validate import ROOT

GATE = ROOT / ".github" / "scripts" / "publish-gate.sh"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.org",
}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, capture_output=True, text=True, check=True).stdout


class GateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "data").mkdir()
        (self.repo / "tests").mkdir()
        (self.repo / "data/snapshot.json").write_text("1\n")
        (self.repo / "tests/test_x.py").write_text("ok\n")
        self.live = self.commit("deployed")

    def commit(self, message):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)
        return git(self.repo, "rev-parse", "HEAD").strip()

    def gate(self, event, live=None, url="https://127.0.0.1:9"):
        env = {**ENV, "PQC_LIVE_URL": url}
        env.pop("PQC_LIVE_COMMIT", None)
        if live is not None:
            env["PQC_LIVE_COMMIT"] = live
        r = subprocess.run([str(GATE), event], cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip(), r.stderr

    def test_collect_commit_that_only_changes_data_skips_the_unit_tests(self):
        (self.repo / "data/snapshot.json").write_text("2\n")
        self.commit("data: collect")
        out, why = self.gate("workflow_run", self.live)
        self.assertEqual(out, "run_tests=false")
        self.assertIn("only data/ changed", why)

    def test_several_collect_commits_in_a_row_still_skip(self):
        for n in (2, 3, 4):
            (self.repo / "data/snapshot.json").write_text(f"{n}\n")
            self.commit(f"data: collect {n}")
        self.assertEqual(self.gate("workflow_run", self.live)[0], "run_tests=false")

    def test_a_deliberately_broken_test_does_not_matter_when_it_is_already_live(self):
        """The test is broken, but it was in the deployed commit: only data changed since."""
        (self.repo / "tests/test_x.py").write_text("assert False\n")
        broken_but_live = self.commit("fragile test")
        (self.repo / "data/snapshot.json").write_text("2\n")
        self.commit("data: collect")
        self.assertEqual(self.gate("workflow_run", broken_but_live)[0], "run_tests=false")

    def test_code_changed_since_the_live_commit_runs_the_tests_even_for_collect(self):
        (self.repo / "tests/test_x.py").write_text("changed\n")
        self.commit("code change that never deployed")
        (self.repo / "data/snapshot.json").write_text("2\n")
        self.commit("data: collect")
        out, why = self.gate("workflow_run", self.live)
        self.assertEqual(out, "run_tests=true")
        self.assertIn("tests/test_x.py", why)

    def test_every_other_event_runs_the_tests(self):
        (self.repo / "data/snapshot.json").write_text("2\n")
        self.commit("data: only")
        for event in ("push", "workflow_dispatch", "schedule", "pull_request"):
            self.assertEqual(self.gate(event, self.live)[0], "run_tests=true", event)

    def test_when_the_live_commit_is_unknown_the_tests_run(self):
        out, why = self.gate("workflow_run")  # no override; the address does not answer
        self.assertEqual(out, "run_tests=true")
        self.assertIn("cannot tell which commit is live", why)

    def test_a_live_commit_missing_from_the_clone_runs_the_tests(self):
        self.assertEqual(self.gate("workflow_run", "f" * 40)[0], "run_tests=true")


class WorkflowWiringTests(unittest.TestCase):
    def setUp(self):
        import yaml

        self.wf = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())
        self.steps = {s.get("name"): s for s in self.wf["jobs"]["build"]["steps"]}

    def test_unit_tests_depend_only_on_the_gate(self):
        tests = self.steps["Run tests"]
        self.assertEqual(tests["if"], "steps.gate.outputs.run_tests == 'true'")
        self.assertEqual(self.steps["Decide whether the unit tests are needed"]["id"], "gate")

    def test_validation_and_build_always_run(self):
        for name in ("Validate schemas", "Build site", "Upload Pages artifact"):
            self.assertNotIn("if", self.steps[name], name)

    def test_the_deploy_and_smoke_test_do_not_depend_on_the_test_step_being_run(self):
        self.assertEqual(self.wf["jobs"]["deploy"]["needs"], "build")
        self.assertEqual(self.wf["jobs"]["smoke-test"]["needs"], ["build", "deploy"])
        self.assertNotIn("if", self.wf["jobs"]["deploy"])
        self.assertNotIn("if", self.wf["jobs"]["smoke-test"])

    def test_the_gate_runs_after_validation_and_before_the_tests(self):
        order = [s.get("name") for s in self.wf["jobs"]["build"]["steps"]]
        self.assertLess(
            order.index("Validate schemas"), order.index("Decide whether the unit tests are needed")
        )
        self.assertLess(order.index("Decide whether the unit tests are needed"), order.index("Run tests"))
        self.assertLess(order.index("Run tests"), order.index("Build site"))


if __name__ == "__main__":
    unittest.main()
