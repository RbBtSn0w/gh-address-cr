from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from packaging.version import Version

from gh_address_cr import __version__, cli
from gh_address_cr.core import workflow

ROOT = Path(__file__).resolve().parents[1]
PACKAGED_REQUIREMENTS = ROOT / "src" / "gh_address_cr" / "runtime-requirements.json"


class RuntimeCompatibilityTest(unittest.TestCase):
    def write_requirements(self, root: Path, **overrides: object) -> None:
        payload = json.loads(PACKAGED_REQUIREMENTS.read_text(encoding="utf-8"))
        payload.update(overrides)
        (root / "runtime-requirements.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def compatibility_for(self, requirements_root: Path) -> dict[str, object]:
        with patch("importlib.resources.files", return_value=requirements_root):
            return workflow.runtime_compatibility()

    def assert_incompatible(self, payload: dict[str, object], reason_code: str) -> None:
        self.assertEqual(payload["status"], "incompatible")
        self.assertEqual(payload["reason_code"], reason_code)
        self.assertEqual(payload["waiting_on"], "runtime_compatibility")
        self.assertEqual(payload["exit_code"], 5)
        remediation = payload["remediation"]
        self.assertIsInstance(remediation, dict)
        self.assertIn("installation channel", str(remediation["summary"]))
        self.assertEqual(remediation["command"], "gh-address-cr adapter check-runtime")
        self.assertNotIn("pip install", json.dumps(remediation))

    def test_current_runtime_satisfies_packaged_requirements(self):
        payload = workflow.runtime_compatibility()

        self.assertGreaterEqual(Version(__version__), Version(payload["minimum_runtime_version"]))
        self.assertEqual(payload["status"], "compatible")
        self.assertEqual(payload["reason_code"], "RUNTIME_COMPATIBLE")
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual(payload["required_protocol_version"], "1.1")
        self.assertEqual(payload["supported_protocol_versions"], ["1.1"])
        self.assertEqual(payload["supported_skill_contract_versions"], ["1.1"])

    def test_rejects_runtime_below_minimum_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_requirements(root)
            with patch.object(workflow, "__version__", "3.15.3"):
                payload = self.compatibility_for(root)

        self.assert_incompatible(payload, "RUNTIME_VERSION_INCOMPATIBLE")

    def test_rejects_protocol_outside_required_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_requirements(root)
            with patch.object(workflow, "PROTOCOL_VERSION", "1.0"):
                payload = self.compatibility_for(root)

        self.assert_incompatible(payload, "PROTOCOL_VERSION_INCOMPATIBLE")

    def test_rejects_unsupported_skill_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_requirements(root, skill_contract_version="2.0")
            payload = self.compatibility_for(root)

        self.assert_incompatible(payload, "SKILL_CONTRACT_INCOMPATIBLE")

    def test_rejects_missing_required_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_requirements(root)
            with patch.object(workflow, "_available_runtime_entrypoints", return_value={"python3 -m gh_address_cr"}):
                payload = self.compatibility_for(root)

        self.assert_incompatible(payload, "RUNTIME_ENTRYPOINTS_INCOMPATIBLE")
        self.assertEqual(payload["missing_entrypoints"], ["gh-address-cr"])

    def test_malformed_requirements_fail_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime-requirements.json").write_text("{not-json", encoding="utf-8")
            payload = self.compatibility_for(root)

        self.assert_incompatible(payload, "RUNTIME_REQUIREMENTS_INVALID")

    def test_cli_returns_payload_exit_code(self):
        incompatible = {
            "status": "incompatible",
            "reason_code": "RUNTIME_VERSION_INCOMPATIBLE",
            "waiting_on": "runtime_compatibility",
            "remediation": {
                "summary": "Upgrade through the original installation channel.",
                "command": "gh-address-cr adapter check-runtime",
            },
            "exit_code": 5,
        }
        output = StringIO()
        with patch.object(workflow, "runtime_compatibility", return_value=incompatible), redirect_stdout(output):
            exit_code = cli.main(["adapter", "check-runtime"])

        self.assertEqual(exit_code, 5)
        self.assertEqual(json.loads(output.getvalue()), incompatible)

    def test_check_runtime_does_not_create_session_state(self):
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            env["GH_ADDRESS_CR_STATE_DIR"] = directory
            result = subprocess.run(
                [sys.executable, "-m", "gh_address_cr", "adapter", "check-runtime"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).rglob("session.json")), [])


if __name__ == "__main__":
    unittest.main()
