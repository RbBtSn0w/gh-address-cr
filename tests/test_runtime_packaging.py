import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from gh_address_cr.agent.manifests import validate_capability_manifest

from tests.helpers import RUNTIME_PACKAGE_DIR, SRC_ROOT, PythonScriptTestCase


class RuntimePackagingTest(PythonScriptTestCase):
    def test_runtime_package_imports_from_src(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [sys.executable, "-c", "import gh_address_cr, gh_address_cr.cli; print(gh_address_cr.__version__)"],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((RUNTIME_PACKAGE_DIR / "cli.py").exists())
        self.assertIn("0.1.0", result.stdout)

    def test_installed_runtime_carries_legacy_command_scripts(self):
        install_root = Path(self.temp_dir.name) / "installed"
        shutil.copytree(RUNTIME_PACKAGE_DIR, install_root / "gh_address_cr")
        env = self.env.copy()
        env["PYTHONPATH"] = str(install_root)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import gh_address_cr.cli as cli\n"
                    "result = cli.run_script('session_engine.py', ['--help'])\n"
                    "print(result.returncode)\n"
                    "print(result.stdout)\n"
                ),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "0")
        self.assertIn("usage:", result.stdout)

    def test_session_engine_legacy_script_is_thin_native_delegate(self):
        legacy_script = RUNTIME_PACKAGE_DIR / "legacy_scripts" / "session_engine.py"
        text = legacy_script.read_text(encoding="utf-8")

        self.assertIn("from gh_address_cr.core.session_engine import main", text)
        self.assertNotIn("def default_session", text)
        self.assertNotIn("def load_session", text)
        self.assertNotIn("from python_common import", text)

    def test_cr_loop_legacy_script_is_thin_native_delegate(self):
        legacy_script = RUNTIME_PACKAGE_DIR / "legacy_scripts" / "cr_loop.py"
        text = legacy_script.read_text(encoding="utf-8")

        self.assertIn("from gh_address_cr.core.cr_loop import main", text)
        self.assertNotIn("def handle_batch", text)
        self.assertNotIn("import session_engine as engine", text)
        self.assertNotIn("from python_common import", text)

    def test_control_plane_legacy_script_is_thin_native_delegate(self):
        legacy_script = RUNTIME_PACKAGE_DIR / "legacy_scripts" / "control_plane.py"
        text = legacy_script.read_text(encoding="utf-8")

        self.assertIn("from gh_address_cr.core.control_plane import main", text)
        self.assertNotIn("def run_or_return", text)
        self.assertNotIn("from python_common import", text)

    def test_native_session_engine_exposes_legacy_cli_contract(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from gh_address_cr.core import session_engine\n"
                    "parser = session_engine.build_parser()\n"
                    "print(parser.prog)\n"
                    "print(hasattr(session_engine, 'main'))\n"
                ),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("True", result.stdout)

    def test_native_cr_loop_exposes_legacy_cli_contract(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from gh_address_cr.core import cr_loop\n"
                    "parser = cr_loop.build_parser()\n"
                    "print(parser.prog)\n"
                    "print(hasattr(cr_loop, 'main'))\n"
                    "print(hasattr(cr_loop, 'handle_batch'))\n"
                ),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("True\nTrue", result.stdout)

    def test_native_control_plane_exposes_legacy_cli_contract(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from gh_address_cr.core import control_plane\n"
                    "parser = control_plane.build_parser()\n"
                    "print(parser.prog)\n"
                    "print(hasattr(control_plane, 'main'))\n"
                    "print(hasattr(control_plane, 'run_or_return'))\n"
                ),
            ],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("True\nTrue", result.stdout)

    def test_runtime_module_help_lists_public_commands(self):
        result = self.run_runtime_module("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("review", result.stdout)
        self.assertIn("threads", result.stdout)
        self.assertIn("findings", result.stdout)
        self.assertIn("final-gate", result.stdout)

    def test_runtime_unknown_command_fails_loudly(self):
        result = self.run_runtime_module("unknown-command")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown command", result.stderr.lower())

    def test_runtime_public_command_help_parity(self):
        commands = [
            ("review", "--help"),
            ("threads", "--help"),
            ("findings", "--help"),
            ("adapter", "--help"),
            ("review-to-findings", "--help"),
            ("final-gate", "--help"),
            ("cr-loop", "--help"),
        ]

        for command in commands:
            with self.subTest(command=command):
                result = self.run_runtime_module(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)

    def test_agent_manifest_outputs_runtime_capabilities(self):
        result = self.run_runtime_module("agent", "manifest")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "MANIFEST_READY")
        validate_capability_manifest(payload)
        self.assertIn("coordinator", payload["roles"])
        self.assertIn("triage", payload["roles"])
        self.assertIn("fixer", payload["roles"])
        self.assertIn("verify", payload["actions"])
        self.assertEqual(payload["constraints"]["max_parallel_claims"], 2)
        self.assertIn("action_request.v1", payload["input_formats"])

    def test_missing_gh_preflight_fails_before_session_mutation(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)
        env["PATH"] = str(self.bin_dir)

        result = subprocess.run(
            [sys.executable, "-m", "gh_address_cr", "review", self.repo, self.pr],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "GH_NOT_FOUND")
        self.assertFalse(self.session_file().exists())

    def test_unauthenticated_gh_preflight_fails_before_session_mutation(self):
        gh = self.bin_dir / "gh"
        gh.write_text("#!/bin/sh\nif [ \"$1\" = \"auth\" ]; then exit 1; fi\nexit 0\n", encoding="utf-8")
        gh.chmod(0o755)
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env['PATH']}"

        result = subprocess.run(
            [sys.executable, "-m", "gh_address_cr", "review", self.repo, self.pr],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "GH_AUTH_FAILED")
        self.assertFalse(self.session_file().exists())


if __name__ == "__main__":
    unittest.main()
