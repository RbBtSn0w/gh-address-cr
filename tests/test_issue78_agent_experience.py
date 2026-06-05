import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from gh_address_cr import cli as runtime_cli
from gh_address_cr.agent.responses import ResponseValidationError, validate_workflow_decision
from gh_address_cr.core import session as session_store
from gh_address_cr.core.leases import LeaseConflictError, LeaseSubmissionError, calculate_conflict_keys, claim_lease, submit_lease
from gh_address_cr.core.telemetry import build_efficiency_report, import_external_telemetry

from tests.helpers import CLI_PY, PythonScriptTestCase


class Issue78ActiveScopeTests(PythonScriptTestCase):
    def _write_session(self, repo="octo/example", pr="77", status="ACTIVE"):
        manager = session_store.SessionManager(repo, pr)
        payload = manager.create(status=status)
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

    def test_high_level_command_ignores_inactive_cached_sessions(self):
        self._write_session("octo/example", "77", status="ACTIVE")
        self._write_session("octo/inactive", "12", status="PASSED")
        self._install_fake_gh_for_threads()

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", "--lean"])

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["repo"], "octo/example")
        self.assertEqual(payload["pr_number"], "77")

    def test_high_level_command_fails_loud_when_state_dir_scan_errors(self):
        state_file = self.state_dir / "not-a-directory"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("not a directory", encoding="utf-8")
        self.env["GH_ADDRESS_CR_STATE_DIR"] = str(state_file)

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", "--lean"])

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "NO_ACTIVE_PR_SCOPE")

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
    def test_stale_request_recovery_prevents_blind_retry_loop(self):
        session = {"items": {}, "leases": {}, "lease_events": []}
        item = {"item_id": "github-thread:stale", "path": "src/a.py", "state": "claimed"}
        session["items"][item["item_id"]] = item
        lease = claim_lease(
            session,
            item,
            agent_id="codex-fixer-1",
            role="fixer",
            request_hash="hash-old",
            lease_id="lease-stale",
        )

        with self.assertRaises(LeaseSubmissionError) as caught:
            submit_lease(
                session,
                lease.lease_id,
                agent_id="codex-fixer-1",
                role="fixer",
                item_id=item["item_id"],
                request_hash="hash-new",
            )

        self.assertEqual(caught.exception.reason_code, "STALE_REQUEST_CONTEXT")
        self.assertEqual(caught.exception.recovery_state["recovery_outcome"], "refresh_state")
        self.assertIn("agent next", caught.exception.recovery_state["resume_command"])

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

    def test_file_level_fallback_conflicts_with_hunk_scoped_lease(self):
        file_level = {"item_id": "a", "path": "src/a.py"}
        hunk_level = {"item_id": "b", "path": "src/a.py", "line": 10, "end_line": 12}
        session = {"leases": {}}

        claim_lease(session, file_level, agent_id="a1", role="fixer", request_hash="r1")

        with self.assertRaises(LeaseConflictError):
            claim_lease(session, hunk_level, agent_id="a2", role="fixer", request_hash="r2")

    def test_hunk_scoped_lease_conflicts_with_existing_file_level_fallback(self):
        file_level = {"item_id": "b", "path": "src/a.py"}
        hunk_level = {"item_id": "a", "path": "src/a.py", "line": 10, "end_line": 12}
        session = {"leases": {}}

        claim_lease(session, hunk_level, agent_id="a1", role="fixer", request_hash="r1")

        with self.assertRaises(LeaseConflictError):
            claim_lease(session, file_level, agent_id="a2", role="fixer", request_hash="r2")


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

    def test_command_session_continues_after_unhandled_operation_exception(self):
        request = {
            "operations": [
                {"id": "raises", "argv": ["explode"]},
                {"id": "ok", "argv": ["version"]},
            ]
        }
        request_path = self.state_dir / "commands.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(json.dumps(request), encoding="utf-8")

        def fake_main(argv):
            if argv == ["explode"]:
                raise RuntimeError("boom")
            return 0

        stdout = io.StringIO()
        with patch.object(runtime_cli, "main", fake_main), contextlib.redirect_stdout(stdout):
            exit_code = runtime_cli.handle_command_session(["--input", str(request_path)])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual([step["id"] for step in payload["results"]], ["raises", "ok"])
        self.assertEqual(payload["results"][0]["exit_code"], 2)
        self.assertIn("Unhandled exception: boom", payload["results"][0]["stderr"])
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

    def test_autopilot_trivial_detection_uses_word_boundaries(self):
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
                "body": "Author name typo in the README.",
            }
        }
        manager.save(session)

        result = self.run_cmd([sys.executable, str(CLI_PY), "agent", "orchestrate", "autopilot", self.repo, self.pr])

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["steps"][0]["classification"], "fix")

    def test_autopilot_trivial_detection_rejects_sensitive_identifiers(self):
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
                "body": "Typo around auth_token documentation.",
            }
        }
        manager.save(session)

        result = self.run_cmd([sys.executable, str(CLI_PY), "agent", "orchestrate", "autopilot", self.repo, self.pr])

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertNotIn("classification", payload["steps"][0])
        self.assertTrue(payload["steps"][0]["requires_decision"])

    def test_autopilot_non_trivial_plan_requires_valid_manual_classification_decision(self):
        manager = session_store.SessionManager(self.repo, self.pr)
        session = manager.create(status="ACTIVE")
        session["items"] = {
            "github-thread:1": {
                "item_id": "github-thread:1",
                "item_kind": "github_thread",
                "path": "src/app.py",
                "line": 4,
                "blocking": True,
                "handled": False,
                "state": "open",
                "body": "This branch needs a deeper behavioral decision.",
            }
        }
        manager.save(session)

        result = self.run_cmd([sys.executable, str(CLI_PY), "agent", "orchestrate", "autopilot", self.repo, self.pr])

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        classify_step = payload["steps"][0]
        self.assertEqual(classify_step["command"], "agent classify")
        self.assertNotIn("classification", classify_step)
        self.assertTrue(classify_step["requires_decision"])
        self.assertEqual(classify_step["classification_options"], ["fix", "clarify", "defer", "reject"])
        self.assertEqual(payload["steps"][1]["role"], "triage")
        self.assertTrue(payload["steps"][0]["side_effect"])
        self.assertTrue(payload["steps"][0]["runtime_state_effect"])
        self.assertFalse(payload["steps"][0]["github_side_effect"])
        self.assertTrue(payload["steps"][1]["side_effect"])
        self.assertTrue(payload["steps"][1]["runtime_state_effect"])
        self.assertFalse(payload["steps"][1]["github_side_effect"])
        self.assertTrue(payload["steps"][2]["side_effect"])
        self.assertTrue(payload["steps"][2]["runtime_state_effect"])
        self.assertFalse(payload["steps"][2]["github_side_effect"])

    def test_autopilot_execute_rejection_reports_side_effects_disabled(self):
        manager = session_store.SessionManager(self.repo, self.pr)
        session = manager.create(status="ACTIVE")
        manager.save(session)

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "agent", "orchestrate", "autopilot", self.repo, self.pr, "--execute"]
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "AUTOPILOT_EXECUTION_NOT_ENABLED")
        self.assertFalse(payload["side_effects_enabled"])


class Issue78TrivialFastPathTests(PythonScriptTestCase):
    def test_trivial_docs_fast_path_accepts_words_containing_sensitive_substrings(self):
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
                "body": "Capitalization typo in the author name section.",
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
                "Fixed author typo.",
                "--why",
                "Documentation-only typo.",
                "--validation",
                "docs check=passed",
            ]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "TRIVIAL_FIX_ACCEPTED")

    def test_trivial_docs_fast_path_rejects_sensitive_identifiers(self):
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
                "body": "Typo around secret_key documentation.",
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
