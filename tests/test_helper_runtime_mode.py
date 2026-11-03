"""Test harness isolation cannot silently substitute checkout code for a wheel."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import ROOT, PythonScriptTestCase


class RuntimeModeTests(unittest.TestCase):
    def test_unknown_mode_fails_before_test_setup(self):
        case = PythonScriptTestCase()
        with patch.dict(os.environ, {"GH_ADDRESS_CR_TEST_RUNTIME": "typo"}):
            try:
                with self.assertRaisesRegex(ValueError, "GH_ADDRESS_CR_TEST_RUNTIME"):
                    case.setUp()
            finally:
                if hasattr(case, "temp_dir"):
                    case.tearDown()
                case.doCleanups()

    def test_installed_mode_rejects_a_checkout_import(self):
        # The normal suite intentionally runs against the editable development package.
        import gh_address_cr

        if not Path(gh_address_cr.__file__).resolve().is_relative_to(ROOT):
            self.skipTest("requires the development checkout")
        case = PythonScriptTestCase()
        with patch.dict(os.environ, {"GH_ADDRESS_CR_TEST_RUNTIME": "installed"}):
            try:
                with self.assertRaisesRegex(RuntimeError, "installed runtime"):
                    case.setUp()
            finally:
                case.doCleanups()

    def test_run_cmd_removes_injected_python_environment_in_installed_mode(self):
        # Exercise this execution boundary independently of the setup origin probe.
        case = PythonScriptTestCase()
        case.runtime_mode = "installed"
        with tempfile.TemporaryDirectory() as tmp:
            case.cwd = Path(tmp)
            case.env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHOME": "/missing-python-home"}
            result = case.run_cmd([
                sys.executable, "-c",
                "import json, os; print(json.dumps([os.environ.get('PYTHONPATH'), os.environ.get('PYTHONHOME'), os.getcwd()]))",
            ])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [None, None, str(Path(tmp).resolve())])

    def test_installed_runtime_call_never_uses_the_in_process_cli(self):
        case = PythonScriptTestCase()
        case.runtime_mode = "installed"
        with tempfile.TemporaryDirectory() as tmp:
            case.cwd = Path(tmp)
            case.env = {**os.environ, "DISABLE_TELEMETRY": "1", "PYTHONHOME": "/missing-python-home"}
            with patch("gh_address_cr.cli.main", side_effect=AssertionError("in-process CLI used")):
                result = case.run_runtime_module("--version", check=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsInstance(result, subprocess.CompletedProcess)
