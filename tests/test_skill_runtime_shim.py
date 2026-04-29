import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.helpers import CLI_PY, SKILL_ROOT, SRC_ROOT, PythonScriptTestCase


class SkillRuntimeShimTest(PythonScriptTestCase):
    def test_skill_shim_fails_loudly_when_runtime_missing(self):
        env = self.env.copy()
        env.pop("PYTHONPATH", None)
        env["GH_ADDRESS_CR_DISABLE_LOCAL_SRC_RUNTIME"] = "1"

        result = subprocess.run(
            [sys.executable, str(CLI_PY), "--help"],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime", result.stderr.lower())
        self.assertFalse(self.session_file().exists())

    def test_skill_shim_delegates_to_src_runtime_when_available(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [sys.executable, str(CLI_PY), "--help"],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("review", result.stdout)

    def test_skill_shim_preserves_legacy_public_command_invocation(self):
        env = self.env.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)

        result = subprocess.run(
            [sys.executable, str(CLI_PY), "cr-loop", "--help"],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertIn("cr_loop.py", result.stdout)

    def test_skill_session_engine_script_is_runtime_delegate(self):
        script = SKILL_ROOT / "scripts" / "session_engine.py"
        text = script.read_text(encoding="utf-8")

        self.assertIn("from gh_address_cr.core.session_engine import main", text)
        self.assertNotIn("def default_session", text)
        self.assertNotIn("from python_common import", text)

    def test_skill_cr_loop_script_is_runtime_delegate(self):
        script = SKILL_ROOT / "scripts" / "cr_loop.py"
        text = script.read_text(encoding="utf-8")

        self.assertIn("from gh_address_cr.core.cr_loop import main", text)
        self.assertNotIn("def handle_batch", text)
        self.assertNotIn("import session_engine as engine", text)
        self.assertNotIn("from python_common import", text)

    def test_skill_control_plane_script_is_runtime_delegate(self):
        script = SKILL_ROOT / "scripts" / "control_plane.py"
        text = script.read_text(encoding="utf-8")

        self.assertIn("from gh_address_cr.core.control_plane import main", text)
        self.assertNotIn("def run_or_return", text)
        self.assertNotIn("from python_common import", text)

    def test_skill_shim_rejects_too_old_runtime_before_session_mutation(self):
        runtime_root = self.write_fake_runtime(version="0.0.1", protocol_versions=("1.0",))
        env = self.env.copy()
        env["PYTHONPATH"] = str(runtime_root)
        env["GH_ADDRESS_CR_DISABLE_LOCAL_SRC_RUNTIME"] = "1"

        result = subprocess.run(
            [sys.executable, str(CLI_PY), "--help"],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime_too_old", result.stderr)
        self.assertFalse(self.session_file().exists())

    def test_skill_shim_rejects_unsupported_protocol_before_session_mutation(self):
        runtime_root = self.write_fake_runtime(version="0.1.0", protocol_versions=("2.0",))
        env = self.env.copy()
        env["PYTHONPATH"] = str(runtime_root)
        env["GH_ADDRESS_CR_DISABLE_LOCAL_SRC_RUNTIME"] = "1"

        result = subprocess.run(
            [sys.executable, str(CLI_PY), "--help"],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protocol_unsupported", result.stderr)
        self.assertFalse(self.session_file().exists())

    def test_skill_shim_rejects_missing_runtime_entrypoint_before_session_mutation(self):
        runtime_root = self.write_fake_runtime(version="0.1.0", protocol_versions=("1.0",), include_main=False)
        env = self.env.copy()
        env["PYTHONPATH"] = str(runtime_root)
        env["GH_ADDRESS_CR_DISABLE_LOCAL_SRC_RUNTIME"] = "1"

        result = subprocess.run(
            [sys.executable, str(CLI_PY), "--help"],
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=env,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing_entrypoint", result.stderr)
        self.assertFalse(self.session_file().exists())

    def test_runtime_requirements_file_is_machine_readable(self):
        payload = json.loads((SKILL_ROOT / "runtime-requirements.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["runtime_package"], "gh-address-cr")
        self.assertIn("gh-address-cr", payload["required_entrypoints"])

    def test_skill_payload_has_no_runtime_package_copy(self):
        forbidden = [
            path
            for path in SKILL_ROOT.rglob("*.py")
            if path.parent.name != "scripts" and "references" not in path.parts
        ]

        self.assertEqual(forbidden, [])

    def write_fake_runtime(self, *, version, protocol_versions, include_main=True):
        root = Path(self.temp_dir.name) / "fake-runtime"
        package = root / "gh_address_cr"
        package.mkdir(parents=True)
        package.joinpath("__init__.py").write_text(
            "\n".join(
                [
                    f'__version__ = "{version}"',
                    'PROTOCOL_VERSION = "1.0"',
                    f"SUPPORTED_PROTOCOL_VERSIONS = {tuple(protocol_versions)!r}",
                    'SUPPORTED_SKILL_CONTRACT_VERSIONS = ("1.0",)',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        package.joinpath("cli.py").write_text(
            "def main():\n    return 0\n" if include_main else "VALUE = 1\n",
            encoding="utf-8",
        )
        return root


if __name__ == "__main__":
    unittest.main()
