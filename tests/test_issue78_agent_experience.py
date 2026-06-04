import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from gh_address_cr.agent.responses import ResponseValidationError, validate_workflow_decision
from gh_address_cr.core import session as session_store
from gh_address_cr.core.leases import LeaseConflictError, calculate_conflict_keys, claim_lease
from gh_address_cr.core.telemetry import build_efficiency_report, import_external_telemetry

from tests.helpers import CLI_PY, PythonScriptTestCase


class Issue78ActiveScopeTests(PythonScriptTestCase):
    def _write_session(self, repo="octo/example", pr="77"):
        manager = session_store.SessionManager(repo, pr)
        payload = manager.create(status="ACTIVE")
        manager.save(payload)
        return payload

    def _install_fake_gh_for_threads(self):
        payload = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [],
                        }
                    }
                }
            }
        }
        gh = self.bin_dir / "gh"
        gh.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import sys",
                    "args = sys.argv[1:]",
                    "if args[:2] == ['auth', 'status']:",
                    "    raise SystemExit(0)",
                    "if args[:2] == ['api', 'graphql']:",
                    f"    print(json.dumps({payload!r}))",
                    "    raise SystemExit(0)",
                    "if args[:2] == ['api', 'user']:",
                    "    print(json.dumps({'login': 'agent-login'}))",
                    "    raise SystemExit(0)",
                    "if args[:2] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:",
                    "    print('[]')",
                    "    raise SystemExit(0)",
                    "raise SystemExit(f'unhandled gh args: {args}')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)

    def test_high_level_command_resolves_single_cached_session(self):
        self._write_session()
        self._install_fake_gh_for_threads()

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", "--lean"])

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["repo"], "octo/example")
        self.assertEqual(payload["pr_number"], "77")

    def test_telemetry_ingest_resolves_single_cached_session_with_option_values(self):
        self._write_session()
        payload_path = self.state_dir / "codex-host.json"
        payload_path.write_text(
            json.dumps(
                {
                    "session_id": "codex-run-1",
                    "turns": [
                        {
                            "id": "turn-1",
                            "duration_ms": 10,
                            "status": "success",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                "--source",
                "codex",
                "--format",
                "codex-host-json",
                "--input",
                str(payload_path),
            ]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        imported = json.loads(result.stdout)
        self.assertEqual(imported["status"], "SUCCESS")
        self.assertEqual(imported["repo"], "octo/example")
        self.assertEqual(imported["pr_number"], "77")

    def test_high_level_command_rejects_ambiguous_cached_session(self):
        self._write_session("octo/example", "77")
        self._write_session("octo/other", "12")

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", "--lean"])

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "AMBIGUOUS_PR_SCOPE")

    def test_high_level_command_rejects_partial_explicit_scope_instead_of_using_cache(self):
        self._write_session("octo/example", "77")

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", "octo/explicit", "--lean"])

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "PARTIAL_PR_SCOPE")

    def test_telemetry_command_rejects_partial_explicit_scope_instead_of_using_cache(self):
        self._write_session("octo/example", "77")

        result = self.run_cmd([sys.executable, str(CLI_PY), "telemetry", "summary", "octo/explicit"])

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "PARTIAL_PR_SCOPE")


class Issue78WorkflowDecisionTests(unittest.TestCase):
    def test_valid_json_workflow_decision_contract(self):
        decision = validate_workflow_decision(
            {
                "schema_version": "workflow_decision.v1",
                "request_id": "req-1",
                "item_id": "github-thread:1",
                "decision": "fix",
                "reason": "Reviewer identified a docs typo.",
            }
        )

        self.assertEqual(decision["decision"], "fix")
        self.assertEqual(decision["item_id"], "github-thread:1")

    def test_invalid_json_workflow_decision_fails_fast(self):
        with self.assertRaises(ResponseValidationError) as cm:
            validate_workflow_decision({"schema_version": "workflow_decision.v1", "decision": "fix"})

        self.assertEqual(cm.exception.code, "missing_request_id")


class Issue78LeaseScopeTests(unittest.TestCase):
    def test_hunk_scoped_conflict_keys_allow_non_overlapping_same_file(self):
        first = {"item_id": "a", "path": "src/a.py", "line": 10, "end_line": 12}
        second = {"item_id": "b", "path": "src/a.py", "line": 30, "end_line": 32}
        session = {"leases": {}}

        first_lease = claim_lease(session, first, agent_id="a1", role="fixer", request_hash="r1")
        second_lease = claim_lease(session, second, agent_id="a2", role="fixer", request_hash="r2")

        self.assertIn("hunk:src/a.py:10-12", first_lease.conflict_keys)
        self.assertIn("hunk:src/a.py:30-32", second_lease.conflict_keys)

    def test_hunk_scoped_conflict_keys_reject_overlapping_same_file(self):
        first = {"item_id": "a", "path": "src/a.py", "line": 10, "end_line": 20}
        second = {"item_id": "b", "path": "src/a.py", "line": 15, "end_line": 30}
        session = {"leases": {}}

        claim_lease(session, first, agent_id="a1", role="fixer", request_hash="r1")

        with self.assertRaises(LeaseConflictError):
            claim_lease(session, second, agent_id="a2", role="fixer", request_hash="r2")

    def test_missing_line_metadata_preserves_file_level_fallback(self):
        keys = calculate_conflict_keys({"item_id": "a", "path": "src/a.py"})

        self.assertIn("file:src/a.py", keys)
        self.assertNotIn("hunk:src/a.py", " ".join(keys))

    def test_position_only_metadata_preserves_file_level_fallback(self):
        keys = calculate_conflict_keys({"item_id": "a", "path": "src/a.py", "position": 9})

        self.assertIn("file:src/a.py", keys)
        self.assertNotIn("hunk:src/a.py", " ".join(keys))


class Issue78TelemetryAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": self.temp_dir.name}, clear=False)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_codex_host_json_adapter_normalizes_tokens_and_tool_usage(self):
        raw = json.dumps(
            {
                "session_id": "codex-run-1",
                "turns": [
                    {
                        "id": "turn-1",
                        "started_at": "2026-06-04T01:00:00Z",
                        "duration_ms": 1200,
                        "status": "success",
                        "tokens": {"input": 100, "output": 40},
                        "tool_calls": [{"name": "exec_command", "duration_ms": 300, "status": "success"}],
                    }
                ],
            }
        )

        imported = import_external_telemetry("octo/example", "77", source="codex", fmt="codex-host-json", raw=raw)
        report = build_efficiency_report("octo/example", "77")

        self.assertEqual(imported["status"], "SUCCESS")
        self.assertEqual(report["coverage_label"], "partial")
        self.assertIn("codex", json.dumps(report))
        self.assertIn("token_input_count", json.dumps(report))

    def test_codex_host_json_adapter_accepts_zero_duration_turns(self):
        raw = json.dumps(
            {
                "session_id": "codex-run-1",
                "turns": [
                    {
                        "id": "turn-1",
                        "duration_ms": 0,
                        "status": "success",
                    }
                ],
            }
        )

        imported = import_external_telemetry("octo/example", "77", source="codex", fmt="codex-host-json", raw=raw)

        self.assertEqual(imported["status"], "SUCCESS")
        self.assertEqual(imported["accepted_count"], 1)
        self.assertEqual(imported["rejected_count"], 0)


class Issue78CommandSessionTests(PythonScriptTestCase):
    def test_command_session_emits_discrete_results_and_continues_after_failure(self):
        request = {
            "operations": [
                {"id": "bad", "argv": ["telemetry", "summary"]},
                {"id": "ok", "argv": ["version"]},
            ]
        }

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "command-session", "--input", "-"],
            stdin=json.dumps(request),
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual([step["id"] for step in payload["results"]], ["bad", "ok"])
        self.assertNotEqual(payload["results"][0]["exit_code"], 0)
        self.assertEqual(payload["results"][1]["exit_code"], 0)


class Issue78AutopilotTests(PythonScriptTestCase):
    def test_autopilot_plan_is_dry_run_by_default(self):
        manager = session_store.SessionManager(self.repo, self.pr)
        session = manager.create(status="ACTIVE")
        session["items"] = {
            "github-thread:1": {
                "item_id": "github-thread:1",
                "item_kind": "github_thread",
                "path": "README.md",
                "line": 4,
                "blocking": True,
                "handled": False,
                "state": "open",
                "body": "Typo in the README.",
            }
        }
        manager.save(session)

        result = self.run_cmd([sys.executable, str(CLI_PY), "agent", "orchestrate", "autopilot", self.repo, self.pr])

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "AUTOPILOT_PLAN_READY")
        self.assertFalse(payload["side_effects_enabled"])
        self.assertEqual(payload["steps"][0]["command"], "agent classify")
        self.assertTrue(payload["steps"][0]["side_effect"])
        self.assertTrue(payload["steps"][0]["runtime_state_effect"])
        self.assertFalse(payload["steps"][0]["github_side_effect"])
        self.assertTrue(payload["steps"][1]["side_effect"])
        self.assertTrue(payload["steps"][1]["runtime_state_effect"])
        self.assertFalse(payload["steps"][1]["github_side_effect"])
        self.assertTrue(payload["steps"][2]["side_effect"])
        self.assertTrue(payload["steps"][2]["runtime_state_effect"])
        self.assertFalse(payload["steps"][2]["github_side_effect"])


class Issue78TrivialFastPathTests(PythonScriptTestCase):
    def test_trivial_docs_fast_path_rejects_security_sensitive_thread(self):
        manager = session_store.SessionManager(self.repo, self.pr)
        session = manager.create(status="ACTIVE")
        session["items"] = {
            "github-thread:1": {
                "item_id": "github-thread:1",
                "item_kind": "github_thread",
                "path": "README.md",
                "line": 4,
                "blocking": True,
                "handled": False,
                "state": "open",
                "body": "This token handling section looks unsafe.",
            }
        }
        manager.save(session)

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "agent",
                "trivial-fix",
                self.repo,
                self.pr,
                "github-thread:1",
                "--commit",
                "abc123",
                "--file",
                "README.md",
                "--summary",
                "Fixed typo.",
                "--why",
                "Documentation-only typo.",
                "--validation",
                "docs check=passed",
            ]
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "TRIVIAL_THREAD_NOT_ELIGIBLE")


if __name__ == "__main__":
    unittest.main()
