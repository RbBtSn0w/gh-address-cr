"""scripts/dogfood_env.sh pins an unreleased runtime and prints eval-able exports."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dogfood_env.sh"


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=600, env=env or os.environ.copy()
    )


class DogfoodEnvScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "dogfood"

    def test_unknown_ref_fails_without_printing_exports(self):
        result = run("--ref", "no-such-ref-for-dogfood", "--home", str(self.home))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("is not a commit", result.stderr)

    def test_no_install_without_a_pinned_runtime_fails(self):
        result = run("--no-install", "--home", str(self.home))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_no_install_prints_exports_that_select_the_pinned_venv(self):
        # A stand-in venv: its python is this interpreter, which can import gh_address_cr.
        bin_dir = self.home / "venv" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python").symlink_to(sys.executable)
        cli = bin_dir / "gh-address-cr"
        cli.write_text("#!/bin/sh\necho pinned\n", encoding="utf-8")
        cli.chmod(0o755)

        result = run("--no-install", "--home", str(self.home))
        self.assertEqual(result.returncode, 0, result.stderr)

        shell = subprocess.run(
            ["bash", "-c", 'eval "$1"; gh-address-cr; echo "$GH_ADDRESS_CR_STATE_DIR"', "_", result.stdout],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(shell.stdout.splitlines(), ["pinned", str(self.home / "state")])
        self.assertTrue((self.home / "state").is_dir())

    @unittest.skipUnless(
        os.environ.get("GH_ADDRESS_CR_DOGFOOD_INSTALL_TEST") == "1",
        "set GH_ADDRESS_CR_DOGFOOD_INSTALL_TEST=1 to run the real pip install (needs network and full git history)",
    )
    def test_install_pins_the_resolved_commit(self):
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

        result = run("--ref", "HEAD", "--home", str(self.home))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"vcs {sha[:12]}", result.stdout)


if __name__ == "__main__":
    unittest.main()
