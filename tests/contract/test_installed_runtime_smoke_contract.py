"""Offline domain smoke exercises installed console and module entrypoints in CI."""

import subprocess
import sys
from pathlib import Path

from tests.contract.test_agent_journey_contract import AgentJourneyTestCase
from tests.helpers import ROOT
from tests.installed_runtime import assert_machine_result


class InstalledRuntimeSmokeTests(AgentJourneyTestCase):
    def test_missing_orchestration_state_is_an_expected_domain_error(self):
        for console in (False, True):
            with self.subTest(console=console):
                result = self.invoke(console, "agent", "orchestrate", "status", self.repo, self.pr)
                assert_machine_result(result, exit_code=2, status="FAILED", reason_code="SESSION_ERROR")
        self.assert_fake_github_covered_every_call()

    def test_unresolved_thread_blocks_the_gate_with_a_precise_reason(self):
        for console in (False, True):
            with self.subTest(console=console):
                result = self.invoke(console, "final-gate", self.repo, self.pr, "--machine", "--no-auto-clean")
                payload = assert_machine_result(
                    result, exit_code=5, status="FAILED", reason_code="FINAL_GATE_UNRESOLVED_REMOTE_THREADS"
                )
                self.assertEqual(payload["counts"]["unresolved_remote_threads_count"], 1)
        self.assert_fake_github_covered_every_call()

    def test_runtime_ignores_poisoned_python_paths_in_installed_mode(self):
        if self.runtime_mode != "installed":
            self.skipTest("installed-wheel isolation contract")
        poison = Path(self.temp_dir.name) / "poison"
        (poison / "gh_address_cr").mkdir(parents=True)
        (poison / "gh_address_cr" / "__init__.py").write_text("raise RuntimeError('checkout poison imported')\n")
        self.env.update(PYTHONPATH=str(poison), PYTHONHOME=str(poison))
        # A package in the working directory must not shadow the wheel either.
        (self.checkout / "gh_address_cr.py").write_text("raise RuntimeError('cwd poison imported')\n")
        result = self.invoke(False, "agent", "orchestrate", "status", self.repo, self.pr)
        assert_machine_result(result, exit_code=2, status="FAILED", reason_code="SESSION_ERROR")
        result = self.invoke(True, "agent", "orchestrate", "status", self.repo, self.pr)
        assert_machine_result(result, exit_code=2, status="FAILED", reason_code="SESSION_ERROR")
        self.assertNotIn("PYTHONHOME", self._subprocess_environment())
        self.assertNotIn("PYTHONPATH", self._subprocess_environment())
        self.assertEqual(Path.cwd().resolve(), self.checkout.resolve())

    def test_installed_mode_rejects_a_runner_that_imported_checkout_code(self):
        if self.runtime_mode != "installed":
            self.skipTest("installed-wheel isolation contract")
        env = self._subprocess_environment()
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", f"{__name__}.InstalledRuntimeSmokeTests.test_missing_orchestration_state_is_an_expected_domain_error"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("test runner imported a different runtime", result.stderr)

    def invoke(self, console, *args):
        if console:
            return self.run_cmd([str(Path(sys.executable).parent / "gh-address-cr"), *args])
        return self.run_runtime_module(*args)
