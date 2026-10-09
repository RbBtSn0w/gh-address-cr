"""scripts/dev_setup.sh builds the dev venv without touching the system Python."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dev_setup.sh"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=600)


class DevSetupScriptTests(unittest.TestCase):
    def test_unknown_argument_is_rejected(self):
        result = run("--no-such-flag")

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("unknown argument", result.stderr)

    def test_missing_interpreter_fails_before_creating_a_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            result = run("--python", "no-such-python-for-dev-setup", "--venv", str(venv))

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("interpreter not found", result.stderr)
            self.assertFalse(venv.exists())

    def test_existing_venv_with_an_old_python_is_rejected_before_pip_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            (venv / "bin").mkdir(parents=True)
            fake_python = venv / "bin" / "python"
            fake_python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            fake_python.chmod(0o755)

            result = run("--venv", str(venv))

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("not a working virtual-environment Python 3.12+", result.stderr)
            self.assertIn("failed to run", result.stderr)
            self.assertIn("remove", result.stderr)

    def test_a_venv_path_holding_a_non_venv_interpreter_is_rejected(self):
        base_python = Path(getattr(sys, "_base_executable", sys.executable))
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "not-a-venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").symlink_to(base_python)

            result = run("--venv", str(venv))

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("not a venv", result.stderr)

    def test_explicit_python_is_reported_as_ignored_for_an_existing_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            (venv / "bin").mkdir(parents=True)
            fake_python = venv / "bin" / "python"
            fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_python.chmod(0o755)

            result = run("--python", "python3", "--venv", str(venv))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("only applies to a new venv", result.stderr)

    def test_help_documents_why_a_venv_is_used(self):
        result = run("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--venv", result.stderr)
        self.assertIn("Why a venv", result.stderr)
        self.assertIn("brew link", result.stderr)


class DevSetupDocsTests(unittest.TestCase):
    def test_agents_md_directs_dev_install_to_the_venv_script(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("scripts/dev_setup.sh", text)
        self.assertIn("brew link", text)


if __name__ == "__main__":
    unittest.main()
