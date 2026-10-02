"""Spec 039 ACT-02: a PR with no check runs is a PR state, not a GitHub failure."""

from __future__ import annotations

import json
import subprocess
import unittest

from gh_address_cr.core.command_runner import _subprocess_outcome
from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.errors import GitHubError, GitHubNoChecksError
from gh_address_cr.github.pr_checks import is_pr_checks_command, pr_checks_result

NO_CHECKS_STDERR = "no checks reported on the 'feature/x' branch\n"
AUTH_STDERR = "HTTP 401: Bad credentials (https://api.github.com/graphql)\n"
PENDING_JSON = json.dumps([{"name": "ci", "state": "PENDING", "bucket": "pending"}])
CHECKS_CMD = ["gh", "pr", "checks", "7", "-R", "octo/example", "--json", "name,state,bucket,link,workflow"]


def completed(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess(CHECKS_CMD, returncode, stdout=stdout, stderr=stderr)


class PrChecksResultTests(unittest.TestCase):
    def test_policy_table(self):
        cases = [
            (0, "[]", "", "checks"),
            (8, PENDING_JSON, "", "checks"),
            (1, PENDING_JSON, "", "checks"),
            (1, "", NO_CHECKS_STDERR, "no_checks"),
            # Same exit and empty stdout, but a real failure.
            (1, "", AUTH_STDERR, "error"),
            (4, "", "", "error"),
        ]
        for returncode, stdout, stderr, expected in cases:
            with self.subTest(returncode=returncode, stderr=stderr):
                self.assertEqual(pr_checks_result(returncode, stdout, stderr), expected)

    def test_recognizes_only_gh_pr_checks(self):
        self.assertTrue(is_pr_checks_command(CHECKS_CMD))
        self.assertTrue(is_pr_checks_command(["/opt/homebrew/bin/gh", "pr", "checks", "7"]))
        self.assertFalse(is_pr_checks_command(["gh", "pr", "view", "7"]))
        self.assertFalse(is_pr_checks_command(["gh", "api", "graphql"]))


class ListPrChecksTests(unittest.TestCase):
    def client(self, result):
        return GitHubClient(runner=lambda cmd: result)

    def test_no_checks_raises_a_dedicated_github_error(self):
        with self.assertRaises(GitHubNoChecksError) as ctx:
            self.client(completed(1, "", NO_CHECKS_STDERR)).list_pr_checks("octo/example", "7")
        self.assertEqual(ctx.exception.reason_code, "GITHUB_PR_HAS_NO_CHECKS")
        # final-gate --require-checks treats any GitHubError as blocking; that must not change.
        self.assertIsInstance(ctx.exception, GitHubError)

    def test_auth_failure_is_not_mistaken_for_no_checks(self):
        with self.assertRaises(GitHubError) as ctx:
            self.client(completed(1, "", AUTH_STDERR)).list_pr_checks("octo/example", "7")
        self.assertNotIsInstance(ctx.exception, GitHubNoChecksError)

    def test_pending_checks_are_returned(self):
        rows = self.client(completed(8, PENDING_JSON)).list_pr_checks("octo/example", "7")
        self.assertEqual([row["bucket"] for row in rows], ["pending"])


class SubprocessOutcomeTests(unittest.TestCase):
    def test_pr_checks_states_are_successful_probes(self):
        self.assertEqual(_subprocess_outcome(CHECKS_CMD, completed(1, "", NO_CHECKS_STDERR)), "success")
        self.assertEqual(_subprocess_outcome(CHECKS_CMD, completed(8, PENDING_JSON)), "success")
        self.assertEqual(_subprocess_outcome(CHECKS_CMD, completed(1, "", AUTH_STDERR)), "failure")

    def test_other_commands_keep_exit_code_meaning(self):
        self.assertIsNone(_subprocess_outcome(["gh", "api", "user"], completed(1, "", AUTH_STDERR)))


if __name__ == "__main__":
    unittest.main()
