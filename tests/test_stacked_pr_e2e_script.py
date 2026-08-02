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
    @staticmethod
    def manifest():
        run_id = "20260801-120000"
        layers = []
        base = "main"
        for position, name in enumerate(("bottom", "middle", "top"), start=1):
            branch = f"e2e/gh-address-cr-stack-{run_id}-{name}"
            layers.append(
                {
                    "name": name,
                    "position": position,
                    "branch": branch,
                    "base_branch": base,
                    "path": f"e2e/stack-{run_id}-{name}.txt",
                    "head_sha": str(position) * 40,
                    "pr_number": 100 + position,
                    "pr_url": f"https://github.com/owner/demo-repo/pull/{100 + position}",
                    "review_comment_id": 900 + position,
                }
            )
            base = branch
        return {
            "schema_version": "gh_address_cr_stacked_pr_e2e.v1",
            "repo": "owner/demo-repo",
            "run_id": run_id,
            "default_branch": "main",
            "stack_number": 7,
            "stack_node_id": "STACK_7",
            "layers": layers,
        }

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

    def test_exercise_requires_and_verifies_required_check_policy_for_stack_gate(self):
        script = load_script()
        manifest = self.manifest()
        calls = []
        script.verify = lambda payload: {
            "status": "VERIFIED",
            "repo": payload["repo"],
            "stack_number": payload["stack_number"],
        }

        def runtime(arguments, *, accepted_exit_codes=(0,)):
            calls.append(arguments)
            if arguments[0] == "address":
                return {"status": "PASSED"}
            if "--stack" in arguments:
                return {
                    "status": "PASSED",
                    "completion_scope": "stack_segment",
                    "check_requirement": "required",
                    "completion_summary_line": "[gh-address-cr stack: PASSED]",
                    "stack_gate": {
                        "selected_pr_number": "103",
                        "covered_pr_numbers": ["101", "102", "103"],
                        "check_requirement": "required",
                    },
                }
            return {
                "status": "PASSED",
                "completion_scope": "pull_request",
                "completion_summary_line": "[gh-address-cr: PASSED]",
            }

        script.run_runtime_json = runtime

        result = script.exercise(manifest)

        stack_gate_call = next(arguments for arguments in calls if "--stack" in arguments)
        self.assertIn("--require-required-checks", stack_gate_call)
        self.assertEqual(result["stack_gate"]["check_requirement"], "required")

    def test_exercise_rejects_incomplete_stack_gate_scope_evidence(self):
        script = load_script()
        manifest = self.manifest()
        script.verify = lambda payload: {
            "status": "VERIFIED",
            "repo": payload["repo"],
            "stack_number": payload["stack_number"],
        }

        def runtime(arguments, *, accepted_exit_codes=(0,)):
            if arguments[0] == "address":
                return {"status": "PASSED"}
            if "--stack" in arguments:
                return {
                    "status": "PASSED",
                    "completion_scope": "stack_segment",
                    "check_requirement": None,
                    "stack_gate": {
                        "selected_pr_number": "103",
                        "covered_pr_numbers": ["102", "103"],
                        "check_requirement": None,
                    },
                }
            return {"status": "PASSED", "completion_scope": "pull_request"}

        script.run_runtime_json = runtime

        with self.assertRaises(script.SandboxError):
            script.exercise(manifest)

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

    def test_sandbox_marker_requires_a_distinct_token(self):
        script = load_script()
        script.gh_api = lambda endpoint, **kwargs: {
            "name": "contest-production",
            "description": "Latest customer application",
            "archived": False,
            "disabled": False,
        }

        with self.assertRaises(script.SandboxError):
            script.assert_sandbox_repo("owner/contest-production", allow_non_sandbox=False)

    def test_cleanup_rejects_forged_manifest_before_github_mutation(self):
        script = load_script()
        manifest = self.manifest()
        manifest["layers"][1]["branch"] = "release/production"
        calls = []

        def api(endpoint, *, method="GET", payload=None):
            calls.append((method, endpoint, payload))
            raise AssertionError("forged manifest must fail before GitHub access")

        script.gh_api = api
        with self.assertRaises(script.SandboxError):
            script.cleanup(manifest)

        self.assertEqual(calls, [])

    def test_provision_rejects_unsafe_run_id_before_github_mutation(self):
        script = load_script()
        calls = []
        script.assert_sandbox_repo = lambda repo, allow_non_sandbox: {
            "default_branch": "main",
            "archived": False,
            "disabled": False,
        }

        def api(endpoint, *, method="GET", payload=None):
            calls.append((method, endpoint, payload))
            raise AssertionError("unsafe run id must fail before GitHub access")

        script.gh_api = api
        args = script.parser().parse_args(
            [
                "provision",
                "--repo",
                "owner/demo-repo",
                "--run-id",
                "../release",
                "--manifest",
                "/tmp/unused-stack-manifest.json",
            ]
        )

        with self.assertRaises(script.SandboxError):
            script.provision(args)

        self.assertEqual(calls, [])

    def test_manifest_position_type_is_rejected_as_sandbox_error(self):
        script = load_script()
        manifest = self.manifest()
        manifest["layers"][0]["position"] = "bottom"

        with self.assertRaises(script.SandboxError):
            script.validate_fixture_manifest(manifest)

    def test_cleanup_verifies_live_fixture_ownership_before_mutation(self):
        script = load_script()
        manifest = self.manifest()
        calls = []

        def api(endpoint, *, method="GET", payload=None):
            calls.append((method, endpoint, payload))
            if endpoint.endswith("/stacks/7"):
                return {"number": 7, "node_id": "STACK_7", "pull_requests": [{"number": n} for n in (101, 102, 103)]}
            if "/pulls/" in endpoint:
                pr_number = int(endpoint.rsplit("/", 1)[1])
                layer = manifest["layers"][pr_number - 101]
                return {
                    "number": pr_number,
                    "title": f"test: stacked PR E2E {manifest['run_id']} {layer['name']}",
                    "body": "unrelated pull request",
                    "head": {"ref": layer["branch"], "sha": layer["head_sha"]},
                    "base": {"ref": layer["base_branch"]},
                    "stack": {"number": 7, "position": layer["position"], "size": 3},
                }
            raise AssertionError(endpoint)

        script.gh_api = api
        with self.assertRaises(script.SandboxError):
            script.cleanup(manifest)

        self.assertFalse(any(method != "GET" for method, _, _ in calls))

    def test_verify_rejects_member_stack_identity_mismatch(self):
        script = load_script()
        manifest = self.manifest()

        def api(endpoint, *, method="GET", payload=None):
            if endpoint.endswith("/stacks/7"):
                return {"number": 7, "node_id": "STACK_7", "pull_requests": [{"number": n} for n in (101, 102, 103)]}
            if endpoint.endswith("/comments"):
                pr_number = int(endpoint.split("/pulls/", 1)[1].split("/", 1)[0])
                layer = manifest["layers"][pr_number - 101]
                return [
                    {
                        "id": layer["review_comment_id"],
                        "body": script.fixture_review_body(layer["name"]),
                        "path": layer["path"],
                    }
                ]
            if "/pulls/" in endpoint:
                pr_number = int(endpoint.rsplit("/", 1)[1])
                layer = manifest["layers"][pr_number - 101]
                return {
                    "number": pr_number,
                    "title": script.fixture_pull_title(manifest["run_id"], layer["name"]),
                    "body": script.fixture_pull_body(manifest["run_id"], layer["name"], layer["position"]),
                    "head": {"ref": layer["branch"], "sha": layer["head_sha"]},
                    "base": {"ref": layer["base_branch"]},
                    "stack": {
                        "number": 8 if pr_number == 102 else 7,
                        "position": layer["position"],
                        "size": 3,
                    },
                }
            raise AssertionError(endpoint)

        script.gh_api = api

        with self.assertRaises(script.SandboxError):
            script.verify(manifest)

    def test_exercise_refuses_to_resolve_an_unrelated_thread(self):
        script = load_script()
        manifest = self.manifest()
        runtime_calls = []
        script.verify = lambda payload: {"status": "VERIFIED", "stack_number": 7}

        def runtime(arguments, *, accepted_exit_codes=(0,)):
            runtime_calls.append(arguments)
            return {
                "status": "WAITING_FOR_SIMPLE_ADDRESS",
                "item_id": "github-thread:unrelated",
                "threads": [
                    {
                        "item_id": "github-thread:unrelated",
                        "body": "A real reviewer concern.",
                        "path": "src/production.py",
                    }
                ],
            }

        script.run_runtime_json = runtime
        with self.assertRaises(script.SandboxError):
            script.exercise(manifest)

        self.assertEqual(len(runtime_calls), 1)
        self.assertEqual(runtime_calls[0][:3], ["address", "owner/demo-repo", "101"])


if __name__ == "__main__":
    unittest.main()
