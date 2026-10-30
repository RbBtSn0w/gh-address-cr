"""Hidden oracle: the finding is a false positive, so the timeouts stay as designed."""

import subprocess
import unittest
from unittest import mock

from app import preflight
from app.github_client import GH_COMMAND_TIMEOUT_SECONDS


class Oracle(unittest.TestCase):
    def test_timeouts_are_unchanged(self):
        self.assertEqual(preflight._PREFLIGHT_AUTH_TIMEOUT_SECONDS, 30.0)
        self.assertEqual(GH_COMMAND_TIMEOUT_SECONDS, 60.0)

    def test_timeout_still_reports_exit_124(self):
        timeout = subprocess.TimeoutExpired(["gh"], 30.0)
        with mock.patch.object(preflight.subprocess, "run", side_effect=timeout), mock.patch.object(
            preflight.time, "sleep"
        ):
            self.assertEqual(preflight.run_gh_auth_status(["gh", "auth", "status"]).returncode, 124)
