"""Trust and operator-interface contracts for guarded trunk operations."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def job(text, name):
    return re.split(r"\n  [a-z][a-z-]+:\n", text.split(f"\n  {name}:\n", 1)[1], maxsplit=1)[0]


class BranchControlWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github/workflows/branches.yml").read_text()

    def test_manual_approval_is_bound_to_candidate_and_consequences(self):
        dispatch = self.text.split("  workflow_dispatch:\n", 1)[1].split("  workflow_run:\n", 1)[0]
        for name in ("pr_number", "expected_head", "expected_base", "approval", "writers_pause_until_utc"):
            self.assertIn(f"      {name}:\n", dispatch)
        for option in ("readiness", "merge", "confirm-release", "confirm-sync"):
            self.assertIn(f"- {option}", dispatch)
        merge = job(self.text, "guarded-merge")
        self.assertIn("inputs.operation == 'merge'", merge)
        self.assertIn("github.event_name == 'workflow_dispatch'", merge)
        self.assertIn("github.ref == 'refs/heads/main'", merge)
        self.assertIn("group: guarded-trunk-merge", merge)
        self.assertIn("cancel-in-progress: false", merge)
        self.assertIn("GH_TRUNK_MERGE_CREDENTIAL: event-capable", merge)
        self.assertIn("GH_TOKEN: ${{ steps.merge-bot.outputs.token || secrets.SYNC_TOKEN }}", merge)
        self.assertNotIn("|| github.token", merge)
        self.assertIn('--actor "$GITHUB_ACTOR"', merge)
        self.assertIn('BRANCH_GATE_TOKEN: ${{ secrets.BRANCH_GATE_TOKEN }}', merge)
        self.assertIn('GH_TRUNK_READ_TOKEN: ${{ github.token }}', merge)

    def test_automatic_summary_runs_only_trusted_main_code(self):
        readiness = job(self.text, "readiness")
        for block in (readiness, job(self.text, "guarded-merge")):
            self.assertIn("ref: refs/heads/main", block)
            self.assertIn("persist-credentials: false", block)
            self.assertNotIn("ref: ${{ github.event.pull_request.head", block)
            self.assertIn("GITHUB_STEP_SUMMARY", block)
        self.assertIn("pull-requests: write", readiness)
        self.assertNotIn("RELEASE_BOT_PRIVATE_KEY", readiness)
        self.assertIn("BRANCH_GATE_TOKEN: ${{ secrets.BRANCH_GATE_TOKEN }}", readiness)
        self.assertIn('GH_TRUNK_GATE_REQUIRED: "true"', readiness)
        self.assertIn("--publish-summary", readiness)
        self.assertIn("workflow_run:", self.text)
        for producer in ('"Checks / Python"', '"ci"', '"Release"'):
            self.assertIn(producer, self.text.split("permissions:\n", 1)[0])

    def test_reviewed_analyzer_versions_are_consistent(self):
        for file in ('.github/actions/setup-branch-control/action.yml', '.github/workflows/ci.yml',
                     '.github/workflows/release.yml'):
            with self.subTest(file=file):
                text = (ROOT / file).read_text()
                self.assertIn('@semantic-release/commit-analyzer@13.0.1', text)
                self.assertIn('conventional-changelog-conventionalcommits@10.4.1', text)

    def test_checks_completions_do_not_create_sync_proposals(self):
        sync = job(self.text, "sync").split("    steps:", 1)[0]
        self.assertIn("github.event.workflow_run.path == '.github/workflows/release.yml'", sync)
        self.assertIn("github.event.workflow_run.event == 'push'", sync)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", sync)
        self.assertEqual(len(list((ROOT / '.github/workflows').glob('*.yml'))), 5)
