import importlib.util
import unittest
from unittest.mock import patch

from tests.helpers import ROOT


def load_script():
    path = ROOT / "scripts" / "e2e_stacked_pr_sandbox.py"
    spec = importlib.util.spec_from_file_location("e2e_stacked_pr_sandbox", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class StackedPRE2EScriptTests(unittest.TestCase):
    @patch("gh_address_cr.core.command_runner.run_cmd")
    def test_json_payload_is_sent_through_standard_input(self, run):
        script = load_script()
        script.run_cmd = run
        run.return_value.returncode = 0
        run.return_value.stdout = '{"sha":"abc"}'
        run.return_value.stderr = ""

        result = script.gh_api("repos/owner/repo/git/blobs", method="POST", payload={"content": "fixture"})

        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["--input", "-"])
        self.assertEqual(run.call_args.kwargs["stdin"], '{"content": "fixture"}')
        self.assertEqual(result["sha"], "abc")

    def test_default_repository_is_explicit_demo_sandbox(self):
        script = load_script()
        self.assertIn("demo", script.DEFAULT_REPO)

    def test_manifest_is_required_for_every_action(self):
        script = load_script()
        with self.assertRaises(SystemExit):
            script.parser().parse_args(["verify"])

    @patch("gh_address_cr.core.command_runner.run_cmd")
    def test_runtime_uses_current_python_module_and_accepts_declared_exit(self, run):
        script = load_script()
        script.run_cmd = run
        run.return_value.returncode = 5
        run.return_value.stdout = '{"status":"WAITING_FOR_SIMPLE_ADDRESS"}'
        run.return_value.stderr = ""

        result = script.run_runtime_json(["address", "owner/repo", "1", "--lean"], accepted_exit_codes=(0, 5))

        self.assertEqual(run.call_args.args[0][:3], [script.sys.executable, "-m", "gh_address_cr"])
        self.assertEqual(result["status"], "WAITING_FOR_SIMPLE_ADDRESS")

    def test_non_sandbox_repository_is_rejected_before_mutation(self):
        script = load_script()
        script.gh_api = lambda endpoint, **kwargs: {
            "name": "production",
            "description": "Customer application",
            "archived": False,
            "disabled": False,
        }
        with self.assertRaises(script.SandboxError):
            script.assert_sandbox_repo("owner/production", allow_non_sandbox=False)


if __name__ == "__main__":
    unittest.main()
