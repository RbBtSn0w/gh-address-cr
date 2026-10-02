"""A malformed <owner/repo> <pr_number> target fails fast, before any state or GitHub work.

A caller whose shell passes "owner/repo 123" as one argument (zsh does not
word-split an unquoted variable) shifts every positional: the item id lands in
pr_number. Each entry point must name the malformed target instead of reporting
a downstream symptom, and must not create a workspace for it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from gh_address_cr.core import paths, protocol_codes

ROOT = Path(__file__).resolve().parents[1]


class PrTargetValidatorTests(unittest.TestCase):
    def test_rejects_malformed_repositories(self):
        for repo in ("", "noslash", "o r/x", "o/r 330", "o/r/x", "o/.", "o/..", "/r", "o/", "-o/r"):
            with self.subTest(repo=repo):
                with self.assertRaises(paths.PathResolutionError) as context:
                    paths.validate_pr_target(repo, "1")
                self.assertEqual(context.exception.reason_code, protocol_codes.INVALID_REPO)

    def test_rejects_malformed_pr_numbers(self):
        for pr_number in ("", "0", "-1", "1a", "abc", "github-thread:PRRT_x", "01"):
            with self.subTest(pr_number=pr_number):
                with self.assertRaises(paths.PathResolutionError) as context:
                    paths.validate_pr_target("o/r", pr_number)
                self.assertEqual(context.exception.reason_code, protocol_codes.INVALID_PR_NUMBER)

    def test_accepts_well_formed_targets(self):
        for repo, pr_number in (("my-org/repo.name", "123"), ("o/r_x", "1"), ("RbBtSn0w/gh-address-cr", 330)):
            with self.subTest(repo=repo, pr_number=pr_number):
                paths.validate_pr_target(repo, pr_number)

    def test_workspace_paths_refuse_a_malformed_repository(self):
        for repo in ("o/r 330", "o/..", "o/r/x"):
            with self.subTest(repo=repo):
                with self.assertRaises(paths.PathResolutionError):
                    paths.workspace_dir(repo, "1")

    def test_errors_do_not_echo_the_rejected_value(self):
        for repo, pr_number in (("o/r ghp_secretvalue", "1"), ("o/r", "alice@example.com")):
            with self.subTest(repo=repo, pr_number=pr_number):
                with self.assertRaises(paths.PathResolutionError) as context:
                    paths.validate_pr_target(repo, pr_number)
                self.assertNotIn("ghp_secretvalue", str(context.exception))
                self.assertNotIn("alice@example.com", str(context.exception))


class SubmitFeedbackAuditScopeTests(unittest.TestCase):
    def scope(self, using_repo, using_pr):
        from gh_address_cr.commands.submit_feedback import DEFAULT_FEEDBACK_PR, audit_scope

        args = Namespace(target_repo="owner/feedback-target", using_repo=using_repo, using_pr=using_pr)
        return audit_scope(args), DEFAULT_FEEDBACK_PR

    def test_well_formed_context_audits_beside_the_pr_session(self):
        (scope, _) = self.scope("o/r", "12")
        self.assertEqual(scope, ("o/r", "12"))

    def test_malformed_context_audits_in_the_feedback_workspace(self):
        (scope, feedback) = self.scope("/private ghp_secretvalue", "alice@example.com")
        self.assertEqual(scope, ("owner/feedback-target", feedback))
        (scope, feedback) = self.scope("o/r", "alice@example.com")
        self.assertEqual(scope, ("o/r", feedback))
        (scope, feedback) = self.scope(None, None)
        self.assertEqual(scope, ("owner/feedback-target", feedback))


class PrTargetCliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"

    def run_cli(self, *argv: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        env = os.environ.copy()
        env.update(
            {
                "GH_ADDRESS_CR_STATE_DIR": str(self.state),
                "DISABLE_TELEMETRY": "1",
                "PYTHONPATH": str(ROOT / "src"),
            }
        )
        result = subprocess.run(
            [sys.executable, "-m", "gh_address_cr", *argv],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotIn("Traceback", result.stderr)
        return result, json.loads(result.stdout)

    def assert_no_workspace(self):
        workspaces = [path for path in self.state.rglob("pr-*")] if self.state.exists() else []
        self.assertEqual(workspaces, [])

    def test_resolve_closed_with_unsplit_target_names_the_repository(self):
        result, payload = self.run_cli(
            "agent", "resolve", "o/r 330", "github-thread:PRRT_x", "--closed",
            "--commit", "abc1234", "--files", "a.py", "--summary", "s", "--why", "w", "--validation", "t=passed",
        )  # fmt: skip

        self.assertEqual(result.returncode, 5)
        self.assertEqual(payload["reason_code"], protocol_codes.INVALID_REPO)
        self.assertEqual(payload["waiting_on"], "pr_scope")
        self.assertIn("separate arguments", payload["next_action"])
        self.assert_no_workspace()

    def test_agent_publish_rejects_a_non_numeric_pr_number(self):
        result, payload = self.run_cli("agent", "publish", "o/r", "abc")

        self.assertEqual(result.returncode, 5)
        self.assertEqual(payload["reason_code"], protocol_codes.INVALID_PR_NUMBER)
        self.assert_no_workspace()

    def test_address_reports_a_malformed_repository_without_a_traceback(self):
        result, payload = self.run_cli("address", "noslash", "1", "--lean")

        self.assertEqual(result.returncode, 5)
        self.assertEqual(payload["reason_code"], protocol_codes.INVALID_REPO)
        self.assertEqual(payload["waiting_on"], "pr_scope")
        self.assertIsNone(payload["artifact_path"])
        self.assert_no_workspace()

    def test_address_rejects_a_non_numeric_pr_number_without_a_workspace(self):
        result, payload = self.run_cli("address", "o/r", "abc", "--lean")

        self.assertEqual(result.returncode, 5)
        self.assertEqual(payload["reason_code"], protocol_codes.INVALID_PR_NUMBER)
        self.assertIsNone(payload["artifact_path"])
        self.assert_no_workspace()

    def test_summary_artifact_path_does_not_create_the_workspace(self):
        from unittest.mock import patch

        from gh_address_cr.commands.high_level import _default_artifact_path

        with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state)}):
            artifact_path = _default_artifact_path("o/r", "12")
            self.assertIsNone(_default_artifact_path("o/r", "abc"))

        self.assertEqual(artifact_path, str(self.state / "o__r" / "pr-12"))
        self.assertFalse(self.state.exists())

    def test_final_gate_rejects_a_non_numeric_pr_number(self):
        result, payload = self.run_cli("final-gate", "o/r", "abc")

        self.assertEqual(result.returncode, 5)
        self.assertEqual(payload["reason_code"], protocol_codes.INVALID_PR_NUMBER)
        self.assert_no_workspace()


if __name__ == "__main__":
    unittest.main()
