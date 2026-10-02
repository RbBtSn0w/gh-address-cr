"""Tests never reach the real GitHub CLI or API (spawned from the Spec 039 R3 hermeticity finding)."""

from __future__ import annotations

import shutil
import subprocess
import unittest

from tests import GH_GUARD_DIR, GH_GUARD_MESSAGE


class HermeticGitHubCliContractTest(unittest.TestCase):
    def test_gh_on_path_is_the_test_guard(self):
        resolved = shutil.which("gh")

        self.assertIsNotNone(resolved)
        self.assertEqual(str(GH_GUARD_DIR), str(__import__("pathlib").Path(resolved).parent))

    def test_guard_fails_fast_without_network(self):
        result = subprocess.run(["gh", "api", "user"], capture_output=True, text=True, timeout=5)

        self.assertEqual(result.returncode, 1)
        self.assertIn(GH_GUARD_MESSAGE, result.stderr)


if __name__ == "__main__":
    unittest.main()
