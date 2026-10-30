import subprocess
import unittest
from unittest import mock

from app import preflight
from app.github_client import GH_COMMAND_TIMEOUT_SECONDS


class PreflightTests(unittest.TestCase):
    def test_success_runs_once(self):
        ok = subprocess.CompletedProcess(["gh"], 0, "", "")
        with mock.patch.object(preflight.subprocess, "run", return_value=ok) as run:
            self.assertEqual(preflight.run_gh_auth_status(["gh", "auth", "status"]).returncode, 0)
        self.assertEqual(run.call_count, 1)

    def test_timeout_is_exit_124_and_retried_once(self):
        timeout = subprocess.TimeoutExpired(["gh"], preflight._PREFLIGHT_AUTH_TIMEOUT_SECONDS)
        with mock.patch.object(preflight.subprocess, "run", side_effect=timeout) as run, mock.patch.object(
            preflight.time, "sleep"
        ):
            result = preflight.run_gh_auth_status(["gh", "auth", "status"])
        self.assertEqual(result.returncode, 124)
        self.assertEqual(run.call_count, preflight._PREFLIGHT_AUTH_ATTEMPTS)

    def test_both_attempts_fit_inside_one_client_call_budget(self):
        self.assertLessEqual(
            preflight._PREFLIGHT_AUTH_ATTEMPTS * preflight._PREFLIGHT_AUTH_TIMEOUT_SECONDS, GH_COMMAND_TIMEOUT_SECONDS
        )


if __name__ == "__main__":
    unittest.main()
