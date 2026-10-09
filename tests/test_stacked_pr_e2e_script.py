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

    def _live_api(
        self, manifest, *, head_overrides=None, base_overrides=None, merged=(), closed=(), existing_refs=True,
        unstack_error=None,
    ):
        """Fake GitHub for a fixture whose members drifted the way GA rewrites them."""
        head_overrides = head_overrides or {}
        base_overrides = base_overrides or {}
        calls = []

        def api(endpoint, *, method="GET", payload=None):
            calls.append((method, endpoint, payload))
            if endpoint.endswith("/stacks/7"):
                return {"number": 7, "node_id": "STACK_7", "pull_requests": [{"number": n} for n in (101, 102, 103)]}
            if endpoint.endswith("/unstack"):
                if unstack_error:
                    raise self.script.SandboxError(f"GitHub API POST {endpoint} failed: {unstack_error}")
                return None
            if "/comments" in endpoint:
                number = int(endpoint.split("/pulls/")[1].split("/")[0])
                layer = manifest["layers"][number - 101]
                return [{"id": layer["review_comment_id"], "body": f"E2E review fixture for the {layer['name']} stack layer. Resolve through gh-address-cr.", "path": layer["path"]}]
            if "/git/refs/" in endpoint:
                if not existing_refs:
                    raise self.script.SandboxError("GitHub API DELETE failed: Reference does not exist")
                return None
            if "/pulls/" in endpoint:
                number = int(endpoint.rsplit("/", 1)[1])
                layer = manifest["layers"][number - 101]
                return {
                    "number": number,
                    "title": f"test: stacked PR E2E {manifest['run_id']} {layer['name']}",
                    "body": self.script.fixture_pull_body(manifest["run_id"], layer["name"], layer["position"]),
                    "state": "closed" if number in merged or number in closed else "open",
                    "merged_at": "2026-10-08T00:00:00Z" if number in merged else None,
                    "head": {"ref": layer["branch"], "sha": head_overrides.get(number, layer["head_sha"])},
                    "base": {"ref": base_overrides.get(number, layer["base_branch"])},
                    "stack": {"number": 7, "position": layer["position"], "size": 3},
                }
            raise AssertionError(endpoint)

        return api, calls

    def test_refresh_records_rebase_and_retarget_drift_after_proving_ownership(self):
        self.script = load_script()
        manifest = self.manifest()
        api, _ = self._live_api(
            manifest, head_overrides={102: "a" * 40, 103: "b" * 40}, base_overrides={102: "main"}, merged={101}
        )
        self.script.gh_api = api

        result = self.script.refresh(manifest)

        self.assertEqual(result["status"], "REFRESHED")
        self.assertEqual([change["pr_number"] for change in result["changes"]], [102, 103])
        self.assertEqual(manifest["layers"][1]["head_sha"], "a" * 40)
        self.assertEqual(manifest["layers"][1]["base_branch"], "main")
        self.script.validate_fixture_manifest(manifest)

    def test_refresh_rejects_a_base_outside_the_fixture_chain(self):
        self.script = load_script()
        manifest = self.manifest()
        api, _ = self._live_api(manifest, base_overrides={103: "release/other"})
        self.script.gh_api = api

        with self.assertRaises(self.script.SandboxError):
            self.script.refresh(manifest)
        self.assertEqual(manifest["layers"][2]["base_branch"], "e2e/gh-address-cr-stack-20260801-120000-middle")

    def test_refresh_rejects_a_pull_request_that_is_not_the_fixture(self):
        self.script = load_script()
        manifest = self.manifest()
        api, _ = self._live_api(manifest)

        def tampered(endpoint, **kwargs):
            payload = api(endpoint, **kwargs)
            if endpoint.endswith("/pulls/102"):
                payload["body"] = "someone else's pull request"
            return payload

        self.script.gh_api = tampered
        with self.assertRaises(self.script.SandboxError):
            self.script.refresh(manifest)

    def test_cleanup_handles_merged_members_and_deleted_branches_without_closing_merged_prs(self):
        self.script = load_script()
        manifest = self.manifest()
        api, calls = self._live_api(manifest, merged={101, 102}, existing_refs=False)
        self.script.gh_api = api

        result = self.script.cleanup(manifest)

        self.assertEqual(result["status"], "CLEANED")
        closed = [endpoint for method, endpoint, _ in calls if method == "PATCH"]
        self.assertEqual(closed, ["repos/owner/demo-repo/pulls/103"])

    def test_cleanup_ignores_an_unstack_failure_only_when_every_member_is_already_closed(self):
        self.script = load_script()
        manifest = self.manifest()
        api, calls = self._live_api(
            manifest, merged={101, 102}, closed={103}, unstack_error="nothing left to unstack", existing_refs=False
        )
        self.script.gh_api = api

        result = self.script.cleanup(manifest)

        self.assertEqual(result["status"], "CLEANED")
        self.assertFalse([endpoint for method, endpoint, _ in calls if method == "PATCH"])

    def test_cleanup_surfaces_an_unstack_failure_while_a_member_is_still_open(self):
        self.script = load_script()
        manifest = self.manifest()
        api, calls = self._live_api(manifest, merged={101}, unstack_error="HTTP 503 service unavailable")
        self.script.gh_api = api

        with self.assertRaises(self.script.SandboxError) as caught:
            self.script.cleanup(manifest)

        self.assertIn("503", str(caught.exception))
        self.assertFalse([call for call in calls if call[0] in {"PATCH", "DELETE"}])

    def test_cleanup_surfaces_an_unstack_failure_when_nothing_was_merged(self):
        self.script = load_script()
        manifest = self.manifest()
        api, _ = self._live_api(manifest, unstack_error="HTTP 401 bad credentials")
        self.script.gh_api = api

        with self.assertRaises(self.script.SandboxError):
            self.script.cleanup(manifest)

    def test_stack_scenario_runs_gh_stack_in_a_clone_then_refreshes(self):
        self.script = load_script()
        manifest = self.manifest()
        api, _ = self._live_api(manifest)
        self.script.gh_api = api
        commands = []
        self.script.run_local = lambda command, *, cwd: commands.append(command[:3]) or ""

        with patch.object(self.script.time, "sleep"):
            result = self.script.stack_scenario(manifest, "merge-bottom")

        self.assertEqual(result["scenario"], "merge-bottom")
        self.assertTrue(any(command[1:3] == ["stack", "merge"] for command in commands))
        self.assertTrue(any(command[1:3] == ["stack", "checkout"] for command in commands))

    def _runtime_double(self, manifest, *, thread_body=None):
        layer = manifest["layers"][1]
        calls = []

        def runtime(arguments, *, accepted_exit_codes=(0,)):
            calls.append(list(arguments))
            if arguments[0] == "address":
                return {
                    "status": "NEEDS_ACTION",
                    "item_id": "github-thread:T1",
                    "threads": [
                        {
                            "item_id": "github-thread:T1",
                            "body": thread_body
                            or f"E2E review fixture for the {layer['name']} stack layer. Resolve through gh-address-cr.",
                            "path": layer["path"],
                        }
                    ],
                }
            if arguments[0] == "final-gate":
                return {"status": "PASSED", "reason_code": None}
            return {"status": "OK"}

        return runtime, calls

    def test_fix_evidence_resolves_the_middle_thread_as_a_fix_with_validation(self):
        self.script = load_script()
        manifest = self.manifest()
        api, _ = self._live_api(manifest)
        runtime, calls = self._runtime_double(manifest)
        self.script.gh_api = api
        self.script.run_runtime_json = runtime

        result = self.script.fix_evidence(manifest)

        resolve = next(call for call in calls if call[:2] == ["agent", "resolve"])
        self.assertEqual(resolve[2:5], ["owner/demo-repo", "102", "github-thread:T1"])
        self.assertEqual(resolve[resolve.index("--disposition") + 1], "fix")
        self.assertEqual(resolve[resolve.index("--file") + 1], manifest["layers"][1]["path"])
        self.assertIn("--validation", resolve)
        self.assertTrue(any(call[:2] == ["agent", "publish"] for call in calls))
        self.assertEqual(result["scenario"], "fix-evidence")
        self.assertEqual([row["pr_number"] for row in result["layers"]], [101, 102, 103])

    def test_fix_evidence_refuses_an_unrelated_thread(self):
        self.script = load_script()
        manifest = self.manifest()
        api, _ = self._live_api(manifest)
        runtime, calls = self._runtime_double(manifest, thread_body="someone else's review")
        self.script.gh_api = api
        self.script.run_runtime_json = runtime

        with self.assertRaises(self.script.SandboxError):
            self.script.fix_evidence(manifest)
        self.assertFalse(any(call[:2] == ["agent", "resolve"] for call in calls))

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
