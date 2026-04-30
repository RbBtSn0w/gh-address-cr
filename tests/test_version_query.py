import subprocess
import sys
import unittest

from tests.helpers import SRC_ROOT

class VersionQueryTestCase(unittest.TestCase):
    def run_cli(self, args):
        env = {"PYTHONPATH": str(SRC_ROOT)}
        return subprocess.run(
            [sys.executable, "-m", "gh_address_cr", *args],
            capture_output=True,
            text=True,
            env=env
        )

    def test_version_flag(self):
        """T004: Test --version flag"""
        result = self.run_cli(["--version"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("gh-address-cr", result.stdout)
        # We don't assert the exact version here to avoid fragility, 
        # but we check it contains numbers and dots.
        self.assertRegex(result.stdout, r"\d+\.\d+\.\d+")

    def test_version_shorthand_flag(self):
        """T005: Test -v flag"""
        result = self.run_cli(["-v"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("gh-address-cr", result.stdout)
        self.assertRegex(result.stdout, r"\d+\.\d+\.\d+")

    def test_version_subcommand(self):
        """T008: Test version subcommand"""
        result = self.run_cli(["version"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("gh-address-cr", result.stdout)
        self.assertRegex(result.stdout, r"\d+\.\d+\.\d+")
