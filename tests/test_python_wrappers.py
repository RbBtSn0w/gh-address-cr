import contextlib
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from tests.helpers import (
    CLI_PY,
    REVIEW_TO_FINDINGS_PY,
    PythonScriptTestCase,
)


class PythonWrapperCLITest(PythonScriptTestCase):
    def run_findings_ingest(self, payload, *, source="local-agent:test", sync=False):
        args = [
            sys.executable,
            str(CLI_PY),
            "findings",
            self.repo,
            self.pr,
            "--source",
            source,
            "--input",
            "-",
        ]
        if sync:
            args.insert(-2, "--sync")
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        return self.run_cmd(args, stdin=raw)

    def local_items(self):
        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        return [
            item
            for item in session.get("items", {}).values()
            if isinstance(item, dict) and item.get("item_kind") == "local_finding"
        ]

    def install_fake_gh_for_threads(self, nodes):
        payload = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": nodes,
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
        return gh

    def test_cli_help_lists_unified_commands(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--machine", result.stdout)
        self.assertIn("--human", result.stdout)
        self.assertIn("[--human|--lean|--summary]", result.stdout)
        self.assertIn("address", result.stdout)
        self.assertIn("review", result.stdout)
        self.assertIn("threads", result.stdout)
        self.assertIn("findings", result.stdout)
        self.assertIn("adapter", result.stdout)
        self.assertIn("review-to-findings", result.stdout)
        self.assertIn("gh-address-cr review", result.stdout)
        self.assertIn("--input batch-response.json", result.stdout)
        self.assertIn("--homogeneous-reason <why>", result.stdout)
        self.assertNotIn("superpowers", result.stdout)
        self.assertNotIn("cli.py review", result.stdout)
        self.assertNotIn("cr-loop", result.stdout)
        self.assertNotIn("control-plane", result.stdout)
        self.assertNotIn("run-once", result.stdout)
        self.assertNotIn("session-engine", result.stdout)

    def test_cli_telemetry_source_redaction_delegates_to_core(self):
        source = (CLI_PY.parent / "commands" / "telemetry.py").read_text(encoding="utf-8")

        self.assertIn("return core_telemetry._reported_source_label(source)", source)
        self.assertNotIn("core_telemetry._contains_token_marker(source)", source)

    def test_cli_review_help_uses_high_level_alias_text(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "review", "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: gh-address-cr review", result.stdout)
        self.assertIn("High-level PR review entrypoint.", result.stdout)
        self.assertIn("waits for external review findings", result.stdout)
        self.assertIn("re-run the same review command", result.stdout)
        self.assertIn("Default output is a structured JSON summary.", result.stdout)
        self.assertIn("--auto-simple", result.stdout)
        self.assertIn("--human", result.stdout)
        self.assertIn("--machine", result.stdout)
        self.assertNotIn("cr-loop", result.stdout)
        self.assertNotIn("{ingest,local,mixed,remote}", result.stdout)

    def test_cli_address_help_uses_lightweight_alias_text(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "address", "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: gh-address-cr address", result.stdout)
        self.assertIn("Lightweight GitHub thread-only entrypoint.", result.stdout)
        self.assertIn("does not wait for external review findings", result.stdout)
        self.assertIn("Default output is a structured JSON summary.", result.stdout)

    def test_cli_adapter_help_matches_orchestration_behavior(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "adapter", "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: gh-address-cr [--human|--machine] adapter", result.stdout)
        self.assertIn("High-level adapter entrypoint.", result.stdout)
        self.assertIn("prints findings JSON and then runs PR orchestration", result.stdout)
        self.assertIn("including GitHub thread handling", result.stdout)
        self.assertIn("passed through to the adapter command unchanged", result.stdout)
        self.assertNotIn("cr-loop", result.stdout)

    def test_cli_root_help_documents_converter_as_fixed_finding_blocks_only(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("review-to-findings owner/repo 123 --input finding-blocks.md", result.stdout)
        self.assertIn("fixed finding blocks only", result.stdout)
        self.assertIn("submit-feedback --category", result.stdout)
        self.assertNotIn("review-to-findings owner/repo 123 --input review.md", result.stdout)

    def test_cli_unknown_command_hint_omits_hidden_superpowers_command(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "unknown-command"])

        self.assertEqual(result.returncode, 2)
        self.assertIn("Supported commands:", result.stderr)
        self.assertNotIn("superpowers", result.stderr)

    def test_cli_utility_handlers_treat_none_return_as_success(self):
        import gh_address_cr.cli as cli
        from gh_address_cr.commands import review_to_findings, submit_action, submit_feedback

        cases = [
            ("submit-action", submit_action, ["request.json", "--resolution", "fix", "--note", "done"]),
            ("review-to-findings", review_to_findings, ["--input", "-"]),
            ("submit-feedback", submit_feedback, ["--category", "workflow-gap", "--title", "t"]),
        ]

        for command, module, args in cases:
            with self.subTest(command=command):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch.object(module, "main", return_value=None),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    rc = cli.main([command, *args])

                self.assertEqual(rc, 0)

    def test_final_gate_host_hook_fallback_summary_failure_is_fail_open(self):
        from gh_address_cr.commands import final_gate

        with (
            patch.dict(
                os.environ,
                {
                    "GH_ADDRESS_CR_HOST_TELEMETRY_INPUT": str(Path(self.temp_dir.name) / "missing-host.jsonl"),
                    "GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE": "assistant-host",
                },
            ),
            patch.object(final_gate.core_telemetry, "input_unavailable_import_summary", side_effect=OSError("disk full")),
        ):
            result = final_gate.ingest_host_telemetry_from_environment(self.repo, self.pr)

        self.assertIsNone(result)

    def test_final_gate_host_hook_import_storage_error_reports_hook_diagnostic(self):
        from gh_address_cr.commands import final_gate

        feed = Path(self.temp_dir.name) / "host.jsonl"
        feed.write_text("{}\n", encoding="utf-8")

        with (
            patch.dict(
                os.environ,
                {
                    "GH_ADDRESS_CR_HOST_TELEMETRY_INPUT": str(feed),
                    "GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE": "assistant-host",
                },
            ),
            patch.object(final_gate.core_telemetry, "import_external_telemetry", side_effect=OSError("disk full")),
            patch.object(final_gate.core_telemetry, "input_unavailable_import_summary") as unavailable,
        ):
            result = final_gate.ingest_host_telemetry_from_environment(self.repo, self.pr)

        self.assertEqual(result["reason_code"], "TELEMETRY_HOOK_UNAVAILABLE")
        self.assertEqual(result["diagnostics"], ["host telemetry hook import unavailable"])
        unavailable.assert_not_called()
        report = final_gate.core_telemetry.build_efficiency_report(self.repo, self.pr)
        self.assertIn(
            "telemetry import assistant-host: host telemetry hook import unavailable",
            report["diagnostics"],
        )

    def test_python_helper_command_normalization_resolves_relative_paths(self):
        command = [
            sys.executable,
            str(Path("src/gh_address_cr/commands/review_to_findings.py")),
            "--help",
        ]

        normalized = self._normalize_python_module_command(command)

        self.assertEqual(normalized[:3], [sys.executable, "-m", "gh_address_cr.commands.review_to_findings"])
        self.assertEqual(normalized[3:], ["--help"])

    def test_cli_submit_feedback_passthrough_dry_run(self):
        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "submit-feedback",
                "--dry-run",
                "--category",
                "workflow-gap",
                "--title",
                "cli passthrough",
                "--summary",
                "summary",
                "--expected",
                "expected",
                "--actual",
                "actual",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "dry-run")
        self.assertTrue(payload["title"].startswith("[AI Feedback] "))

    def test_cli_review_defaults_to_structured_summary(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "final-gate",
                "--machine",
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(
            set(summary),
            {
                "artifact_path",
                "check_requirement",
                "commands",
                "completion_summary",
                "completion_summary_line",
                "counts",
                "exit_code",
                "failure_codes",
                "gate_scope",
                "item_id",
                "item_kind",
                "logic_validation_signals",
                "next_action",
                "pr_number",
                "reason_code",
                "repo",
                "status",
                "waiting_on",
                "telemetry",
                "completion_summary_guidance",
            },
        )
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["counts"]["blocking_items_count"], 0)
        self.assertIn("pr-77", summary["artifact_path"])
        self.assertEqual(summary["next_action"], "Completion may be claimed.")
        self.assertIsNone(summary["reason_code"])
        self.assertIsNone(summary["waiting_on"])
        self.assertEqual(
            summary["completion_summary_line"],
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: unavailable/low (0 events, 0.0%) | sources: telemetry 0 | duration: no observed duration | slowest: none | issues: none]",
        )
        self.assertEqual(summary["completion_summary"]["line"], summary["completion_summary_line"])
        self.assertEqual(summary["completion_summary"]["source_summary"], "telemetry 0")
        self.assertEqual(summary["completion_summary"]["duration_summary"], "no observed duration")
        self.assertEqual(summary["completion_summary"]["top_operation_summary"], "slowest: none")
        self.assertEqual(summary["completion_summary"]["issue_summary"], "none")
        self.assertIn("efficiency-report.json", summary["completion_summary"]["artifact_summary"])
        self.assertEqual(summary["telemetry"]["coverage_label"], "unavailable")
        self.assertIn("efficiency-report.json", summary["telemetry"]["report_artifact"])
        self.assertEqual(summary["telemetry"]["inefficiency_flags"], [])
        self.assertEqual(summary["commands"]["final_gate"], f"gh-address-cr final-gate {self.repo} {self.pr}")

    def test_cli_final_gate_default_keeps_human_text(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "final-gate",
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Final gate PASSED", result.stdout)
        self.assertNotIn('"status"', result.stdout)

    def test_cli_final_gate_global_machine_flag_emits_structured_summary(self):
        self.install_fake_gh_for_threads([])

        result = self.run_cmd([sys.executable, str(CLI_PY), "--machine", "final-gate", self.repo, self.pr])

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["telemetry"]["coverage_label"], "unavailable")
        self.assertNotIn("Final gate PASSED", result.stdout)

    def test_cli_final_gate_machine_blocked_result_includes_completion_summary_line(self):
        self.install_fake_gh_for_threads(
            [
                {
                    "id": "THREAD_OPEN",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/open.py",
                    "line": 12,
                    "firstComment": {"nodes": [{"url": "https://example.test/thread/open", "body": "Still open."}]},
                    "latestComment": {"nodes": [{"url": "https://example.test/thread/open", "body": "Still open."}]},
                }
            ]
        )

        result = self.run_cmd([sys.executable, str(CLI_PY), "--machine", "final-gate", self.repo, self.pr])

        self.assertEqual(result.returncode, 5)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "FAILED")
        self.assertEqual(summary["reason_code"], "FINAL_GATE_UNRESOLVED_REMOTE_THREADS")
        self.assertEqual(
            summary["completion_summary_line"],
            "[gh-address-cr: FAILED | threads: 1 | reviews: 0 | checks: N/A | telemetry: unavailable/low (0 events, 0.0%) | sources: telemetry 0 | duration: no observed duration | slowest: none | issues: none]",
        )
        self.assertEqual(summary["completion_summary"]["line"], summary["completion_summary_line"])
        self.assertEqual(summary["telemetry"]["inefficiency_flags"], [])

    def test_cli_final_gate_rejects_conflicting_output_flags(self):
        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "final-gate", "--machine", "--human", self.repo, self.pr]
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed with argument", result.stderr)

    def test_cli_final_gate_machine_github_failure_emits_structured_summary(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import sys
sys.stderr.write("gh auth failed\\n")
raise SystemExit(1)
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "final-gate", "--machine", self.repo, self.pr])

        self.assertEqual(result.returncode, 5)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "FINAL_GATE_EVALUATION_FAILED")
        self.assertEqual(summary["waiting_on"], "final_gate")

    def test_cli_review_machine_trailing_flag_emits_structured_summary(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "final-gate",
                "--machine",
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["exit_code"], 0)
        self.assertIsNone(summary["reason_code"])
        self.assertIsNone(summary["waiting_on"])

    def test_cli_review_without_findings_enters_external_review_wait_state(self):
        gh = self.bin_dir / "gh"
        gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "review", self.repo, self.pr])
        self.assertEqual(result.returncode, 6)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "WAITING_FOR_EXTERNAL_REVIEW")
        self.assertEqual(summary["reason_code"], "WAITING_FOR_EXTERNAL_REVIEW")
        self.assertEqual(summary["waiting_on"], "external_review")
        self.assertIn("rerun the same review command", summary["next_action"])
        self.assertEqual(summary["repo"], self.repo)
        request_path = Path(summary["artifact_path"])
        self.assertTrue(request_path.exists())
        self.assertEqual(request_path.name, "producer-request.md")
        self.assertIsNone(summary["counts"]["unresolved_github_threads_count"])
        self.assertIsNone(summary["counts"]["blocking_items_count"])
        self.assertTrue((self.workspace_dir() / "incoming-findings.json").exists())
        self.assertTrue((self.workspace_dir() / "incoming-findings.md").exists())
        self.assertIn("external review producer", result.stderr)
        summary_path = self.workspace_dir() / "last-machine-summary.json"
        self.assertTrue(summary_path.exists())
        persisted = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "WAITING_FOR_EXTERNAL_REVIEW")
        self.assertEqual(persisted["reason_code"], "WAITING_FOR_EXTERNAL_REVIEW")

    def test_cli_review_auto_simple_waits_for_simple_address_without_external_handoff(self):
        self.install_fake_gh_for_threads(
            [
                {
                    "id": "THREAD_SIMPLE",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/simple.py",
                    "line": 7,
                    "comments": {
                        "nodes": [
                            {
                                "url": "https://example.test/thread/simple",
                                "body": "Please fix this thread.",
                                "author": {"login": "reviewer"},
                            }
                        ]
                    },
                    "firstComment": {
                        "nodes": [{"url": "https://example.test/thread/simple", "body": "Please fix this thread."}]
                    },
                    "latestComment": {
                        "nodes": [{"url": "https://example.test/thread/simple", "body": "Please fix this thread."}]
                    },
                }
            ]
        )

        result = self.run_cmd([sys.executable, str(CLI_PY), "review", "--auto-simple", self.repo, self.pr])

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "WAITING_FOR_SIMPLE_ADDRESS")
        self.assertEqual(summary["waiting_on"], "agent_fix")
        self.assertEqual(summary["threads"][0]["thread_id"], "THREAD_SIMPLE")
        self.assertIn("body", summary["threads"][0])
        self.assertIn("url", summary["threads"][0])
        self.assertIn("commands", summary)
        self.assertEqual(summary["commands"]["publish"], f"gh-address-cr agent publish {self.repo} {self.pr}")
        request_path = Path(summary["artifact_path"])
        self.assertTrue(request_path.exists())
        self.assertTrue(request_path.name.startswith("simple-address-request-"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(request["mode"], "simple-address")
        self.assertEqual(request["threads"][0]["thread_id"], "THREAD_SIMPLE")
        self.assertEqual(request["claimable_item_ids"], ["github-thread:THREAD_SIMPLE"])
        self.assertEqual(request["batch_response_skeleton"]["items"][0]["item_id"], "github-thread:THREAD_SIMPLE")
        self.assertEqual(request["batch_response_skeleton"]["items"][0]["request_id"], "<request_id from agent next>")
        self.assertEqual(
            request["commands"],
            {
                "address": f"gh-address-cr address {self.repo} {self.pr} --lean",
                "review_auto_simple": f"gh-address-cr review --auto-simple {self.repo} {self.pr} --lean",
                "threads": f"gh-address-cr threads {self.repo} {self.pr} --lean",
                "classify": f"gh-address-cr agent classify {self.repo} {self.pr} <item_id> --classification fix --note <note>",
                "next": f"gh-address-cr agent next {self.repo} {self.pr} --role fixer --agent-id <agent_id>",
                "batch_next": f"gh-address-cr agent next {self.repo} {self.pr} --batch --agent-id <agent_id>",
                "submit": f"gh-address-cr agent submit {self.repo} {self.pr} --input response.json",
                "resolve": (
                    f"gh-address-cr agent resolve {self.repo} {self.pr} <item_id> "
                    "--commit <sha> --files <paths> --summary <text> --why <text> --validation <cmd=passed>"
                ),
                "resolve_batch": f"gh-address-cr agent resolve {self.repo} {self.pr} --batch --input batch-response.json",
                "resolve_homogeneous": (
                    f"gh-address-cr agent resolve {self.repo} {self.pr} "
                    "--commit <sha> --files <paths> --validation <cmd=passed> --homogeneous-reason <why>"
                ),
                "resolve_stale": (
                    f"gh-address-cr agent resolve {self.repo} {self.pr} "
                    "--commit <sha> --files <paths> --validation <cmd=passed> --stale --match-files"
                ),
                "publish": f"gh-address-cr agent publish {self.repo} {self.pr}",
                "final_gate": f"gh-address-cr final-gate {self.repo} {self.pr}",
            },
        )
        self.assertNotIn("scripts/cli.py", json.dumps(request))
        self.assertIn("--batch --input batch-response.json", request["commands"]["resolve_batch"])
        self.assertIn("--homogeneous-reason", request["commands"]["resolve_homogeneous"])
        self.assertFalse((self.workspace_dir() / "producer-request.md").exists())

    def test_cli_threads_lean_omits_verbose_thread_context(self):
        self.install_fake_gh_for_threads(
            [
                {
                    "id": "THREAD_LEAN",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/lean.py",
                    "line": 17,
                    "comments": {
                        "nodes": [
                            {
                                "url": "https://example.test/thread/lean",
                                "body": "Please fix this long thread body.",
                                "author": {"login": "reviewer"},
                            },
                            {
                                "url": "https://example.test/thread/lean/reply",
                                "body": "Follow-up from agent.",
                                "author": {"login": "agent-login"},
                            },
                        ]
                    },
                }
            ]
        )

        result = self.run_cmd([sys.executable, str(CLI_PY), "threads", self.repo, self.pr, "--lean"])

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["reason_code"], "BLOCKING_ITEMS_REMAIN")
        self.assertIn("commands", summary)
        self.assertEqual(summary["commands"]["address"], f"gh-address-cr address {self.repo} {self.pr} --lean")
        thread = summary["threads"][0]
        self.assertEqual(thread["item_id"], "github-thread:THREAD_LEAN")
        self.assertTrue(thread["claimable"])
        self.assertTrue(thread["reply_evidence_present"])
        self.assertNotIn("body", thread)
        self.assertNotIn("url", thread)
        self.assertNotIn("reply_evidence", thread)

    def test_cli_address_summary_alias_matches_lean_thread_shape(self):
        self.install_fake_gh_for_threads(
            [
                {
                    "id": "THREAD_SUMMARY",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/summary.py",
                    "line": 18,
                    "comments": {
                        "nodes": [
                            {
                                "url": "https://example.test/thread/summary",
                                "body": "Please fix this body.",
                                "author": {"login": "reviewer"},
                            }
                        ]
                    },
                }
            ]
        )

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr, "--summary"])

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        thread = summary["threads"][0]
        self.assertEqual(thread["thread_id"], "THREAD_SUMMARY")
        self.assertTrue(thread["claimable"])
        self.assertFalse(thread["reply_evidence_present"])
        self.assertIn("resolve_batch", summary["commands"])
        self.assertNotIn("body", thread)

    def test_cli_active_pr_uses_open_pr_for_current_branch(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import sys",
                    "args = sys.argv[1:]",
                    "if args[:2] == ['pr', 'list']:",
                    "    assert '--state' in args and args[args.index('--state') + 1] == 'open'",
                    "    assert '--head' in args and args[args.index('--head') + 1] == 'feature/agent'",
                    "    print(json.dumps([{'number': 77, 'url': 'https://github.com/octo/example/pull/77', 'headRefName': 'feature/agent', 'state': 'OPEN'}]))",
                    "    raise SystemExit(0)",
                    "raise SystemExit(f'unhandled gh args: {args}')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "active-pr", "--repo", self.repo, "--head", "feature/agent"]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ACTIVE_PR_FOUND")
        self.assertEqual(payload["repo"], self.repo)
        self.assertEqual(payload["pr_number"], "77")
        self.assertEqual(payload["state"], "OPEN")

    def test_cli_active_pr_fails_loudly_without_open_pr(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import sys",
                    "args = sys.argv[1:]",
                    "if args[:2] == ['pr', 'list']:",
                    "    print(json.dumps([]))",
                    "    raise SystemExit(0)",
                    "raise SystemExit(f'unhandled gh args: {args}')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "active-pr", "--repo", self.repo, "--head", "feature/agent"]
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "NO_ACTIVE_PR")
        self.assertEqual(payload["reason_code"], "NO_ACTIVE_PR")
        self.assertIn("--state open", payload["next_action"])

    def test_cli_active_pr_fails_loudly_for_ambiguous_open_prs(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import sys",
                    "args = sys.argv[1:]",
                    "if args[:2] == ['pr', 'list']:",
                    "    assert '--state' in args and args[args.index('--state') + 1] == 'open'",
                    "    print(json.dumps([{'number': 77, 'url': 'https://github.com/octo/example/pull/77', 'state': 'OPEN'}, {'number': 78, 'url': 'https://github.com/octo/example/pull/78', 'state': 'OPEN'}]))",
                    "    raise SystemExit(0)",
                    "raise SystemExit(f'unhandled gh args: {args}')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "active-pr", "--repo", self.repo, "--head", "feature/agent"]
        )

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "AMBIGUOUS_ACTIVE_PR")
        self.assertEqual(payload["reason_code"], "AMBIGUOUS_ACTIVE_PR")
        self.assertEqual(len(payload["pull_requests"]), 2)

    def test_cli_active_pr_rejects_invalid_open_pr_response(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import sys",
                    "args = sys.argv[1:]",
                    "if args[:2] == ['pr', 'list']:",
                    "    print(json.dumps([{'url': 'https://github.com/octo/example/pull/77', 'state': 'OPEN'}]))",
                    "    raise SystemExit(0)",
                    "raise SystemExit(f'unhandled gh args: {args}')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "active-pr", "--repo", self.repo, "--head", "feature/agent"]
        )

        self.assertEqual(result.returncode, 5)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ACTIVE_PR_LOOKUP_FAILED")
        self.assertEqual(payload["reason_code"], "ACTIVE_PR_INVALID_RESPONSE")
        self.assertIn("gh pr list", payload["next_action"])

    def test_cli_address_matches_review_auto_simple_for_unresolved_threads(self):
        self.install_fake_gh_for_threads(
            [
                {
                    "id": "THREAD_ADDRESS",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/address.py",
                    "line": 14,
                    "comments": {
                        "nodes": [
                            {
                                "url": "https://example.test/thread/address",
                                "body": "Please fix address path.",
                                "author": {"login": "reviewer"},
                            }
                        ]
                    },
                    "firstComment": {
                        "nodes": [{"url": "https://example.test/thread/address", "body": "Please fix address path."}]
                    },
                    "latestComment": {
                        "nodes": [{"url": "https://example.test/thread/address", "body": "Please fix address path."}]
                    },
                }
            ]
        )

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr])

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "WAITING_FOR_SIMPLE_ADDRESS")
        self.assertEqual(summary["waiting_on"], "agent_fix")
        self.assertEqual(summary["threads"][0]["thread_id"], "THREAD_ADDRESS")
        request_path = Path(summary["artifact_path"])
        self.assertTrue(request_path.exists())
        request = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(request["claimable_item_ids"], ["github-thread:THREAD_ADDRESS"])

    def test_cli_address_simple_request_includes_stale_threads_as_claimable_items(self):
        self.install_fake_gh_for_threads(
            [
                {
                    "id": "THREAD_STALE",
                    "isResolved": False,
                    "isOutdated": True,
                    "path": "src/stale.py",
                    "line": 21,
                    "comments": {
                        "nodes": [
                            {
                                "url": "https://example.test/thread/stale",
                                "body": "Please fix stale thread.",
                                "author": {"login": "reviewer"},
                            }
                        ]
                    },
                    "firstComment": {
                        "nodes": [{"url": "https://example.test/thread/stale", "body": "Please fix stale thread."}]
                    },
                    "latestComment": {
                        "nodes": [{"url": "https://example.test/thread/stale", "body": "Please fix stale thread."}]
                    },
                }
            ]
        )

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr])

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        request = json.loads(Path(summary["artifact_path"]).read_text(encoding="utf-8"))
        self.assertEqual(summary["reason_code"], "WAITING_FOR_SIMPLE_ADDRESS")
        self.assertEqual(summary["threads"][0]["state"], "stale")
        self.assertEqual(summary["threads"][0]["status"], "STALE")
        self.assertEqual(request["claimable_item_ids"], ["github-thread:THREAD_STALE"])

    def test_cli_doctor_reports_github_and_state_dir_checks(self):
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
                    "if args[:2] == ['api', 'user']:",
                    "    print(json.dumps({'login': 'agent-login'}))",
                    "    raise SystemExit(0)",
                    "if args[:2] == ['repo', 'view']:",
                    "    print(json.dumps({'nameWithOwner': args[2]}))",
                    "    raise SystemExit(0)",
                    "raise SystemExit(f'unhandled gh args: {args}')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "doctor", self.repo, self.pr])

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["reason_code"], "DOCTOR_PASSED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual({check["name"] for check in summary["checks"]}, {"gh_available", "gh_auth", "gh_viewer", "repo_access", "state_dir", "workspace_dir"})

    def test_cli_doctor_help_prints_usage_without_running_checks(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "doctor", "--help"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: gh-address-cr doctor", result.stdout)
        self.assertIn("Runtime diagnostics entrypoint.", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_cli_address_accepts_pr_url_target(self):
        self.install_fake_gh_for_threads([])

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", f"https://github.com/{self.repo}/pull/{self.pr}"])

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["reason_code"], "PASSED")

    def test_cli_address_rejects_existing_blocking_local_findings(self):
        findings = Path(self.temp_dir.name) / "findings.json"
        findings.write_text(
            json.dumps(
                [
                    {
                        "title": "Local finding",
                        "body": "This local finding makes simple address ineligible.",
                        "path": "src/local.py",
                        "line": 9,
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.run_cmd([sys.executable, str(CLI_PY), "findings", self.repo, self.pr, "--input", str(findings)])
        self.install_fake_gh_for_threads([])

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr])

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "AUTO_SIMPLE_NOT_ELIGIBLE")
        self.assertEqual(summary["waiting_on"], "local_findings")
        self.assertIn("normal review", summary["next_action"])

    def test_cli_review_auto_simple_rejects_local_findings_without_switching_commands(self):
        findings = Path(self.temp_dir.name) / "findings.json"
        findings.write_text(
            json.dumps(
                [
                    {
                        "title": "Local finding",
                        "body": "This local finding makes simple address ineligible.",
                        "path": "src/local.py",
                        "line": 9,
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.run_cmd([sys.executable, str(CLI_PY), "findings", self.repo, self.pr, "--input", str(findings)])
        self.install_fake_gh_for_threads([])

        result = self.run_cmd([sys.executable, str(CLI_PY), "review", "--auto-simple", self.repo, self.pr])

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "AUTO_SIMPLE_NOT_ELIGIBLE")
        self.assertEqual(summary["waiting_on"], "local_findings")
        self.assertIn("rerun this command", summary["next_action"])
        self.assertNotIn("rerun address", summary["next_action"])

    def test_cli_address_does_not_emit_simple_request_for_local_gate_failures(self):
        findings = Path(self.temp_dir.name) / "findings.json"
        findings.write_text(
            json.dumps(
                [
                    {
                        "title": "Local finding",
                        "body": "Closed local finding is missing validation.",
                        "path": "src/local.py",
                        "line": 9,
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.run_cmd([sys.executable, str(CLI_PY), "findings", self.repo, self.pr, "--input", str(findings)])
        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        item = next(iter(session["items"].values()))
        item["state"] = "fixed"
        item["status"] = "CLOSED"
        item["blocking"] = False
        self.session_file().write_text(json.dumps(session, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.install_fake_gh_for_threads([])

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr])

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "AUTO_SIMPLE_NOT_ELIGIBLE")
        self.assertEqual(summary["waiting_on"], "local_findings")
        self.assertFalse(list(self.workspace_dir().glob("simple-address-request-*.json")))

    def test_cli_findings_help_mentions_source_required_for_sync(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "findings", "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: gh-address-cr findings", result.stdout)
        self.assertIn("--source <producer_id>", result.stdout)
        self.assertIn("--sync", result.stdout)
        self.assertIn("requires --source", result.stdout)

    def test_cli_review_accepts_pr_url_target(self):
        gh = self.bin_dir / "gh"
        gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "review",
                f"https://github.com/{self.repo}/pull/{self.pr}",
            ]
        )
        self.assertEqual(result.returncode, 6)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "WAITING_FOR_EXTERNAL_REVIEW")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["reason_code"], "WAITING_FOR_EXTERNAL_REVIEW")

    def test_cli_adapter_accepts_pr_url_target(self):
        adapter = Path(self.temp_dir.name) / "adapter.py"
        adapter.write_text("import json\nprint(json.dumps([]))\n", encoding="utf-8")

        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "adapter",
                f"https://github.com/{self.repo}/pull/{self.pr}",
                sys.executable,
                str(adapter),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)

    def test_cli_review_auto_ingests_handoff_json_without_explicit_input(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        (self.workspace_dir() / "incoming-findings.json").write_text("[]\n", encoding="utf-8")

        result = self.run_cmd([sys.executable, str(CLI_PY), "review", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["reason_code"], "PASSED")
        self.assertIsNone(summary["waiting_on"])

    def test_cli_review_continues_after_empty_synced_findings_result(self):
        self.install_fake_gh_for_threads([])

        first = self.run_cmd([sys.executable, str(CLI_PY), "review", self.repo, self.pr])
        self.assertEqual(first.returncode, 6)
        first_summary = json.loads(first.stdout)
        self.assertEqual(first_summary["status"], "WAITING_FOR_EXTERNAL_REVIEW")

        synced = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "findings",
                self.repo,
                self.pr,
                "--input",
                "-",
                "--sync",
                "--source",
                "code-review",
            ],
            stdin="[]\n",
        )
        self.assertEqual(synced.returncode, 0, synced.stderr)
        synced_summary = json.loads(synced.stdout)
        self.assertIn(f"gh-address-cr review {self.repo} {self.pr}", synced_summary["next_action"])

        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        producer_result = session["handoff"]["producer_results"]["code-review"]
        self.assertEqual(producer_result["status"], "submitted")
        self.assertEqual(producer_result["findings_count"], 0)
        self.assertTrue(producer_result["sync_enabled"])

        second = self.run_cmd([sys.executable, str(CLI_PY), "review", self.repo, self.pr])
        self.assertEqual(second.returncode, 0, second.stderr)
        second_summary = json.loads(second.stdout)
        self.assertEqual(second_summary["status"], "PASSED")
        self.assertEqual(second_summary["reason_code"], "PASSED")
        self.assertNotEqual(second_summary["reason_code"], "WAITING_FOR_EXTERNAL_REVIEW")

    def test_cli_findings_rejects_blank_input_without_producer_result(self):
        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "findings",
                self.repo,
                self.pr,
                "--input",
                "-",
                "--sync",
                "--source",
                "code-review",
            ],
            stdin=" \n\t",
        )
        self.assertEqual(result.returncode, 2)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "INVALID_FINDINGS_INPUT")
        self.assertIn("Use [] for an explicit empty producer result", summary["next_action"])

        self.assertFalse(self.session_file().exists())

    def test_cli_findings_missing_input_path_returns_structured_error_without_session_mutation(self):
        missing = Path(self.temp_dir.name) / "missing-findings.json"

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "findings", self.repo, self.pr, "--input", str(missing)]
        )

        self.assertEqual(result.returncode, 2)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "INVALID_FINDINGS_INPUT")
        self.assertIn("missing-findings.json", summary["next_action"])
        self.assertFalse(self.session_file().exists())

    def test_cli_review_continues_after_non_empty_synced_findings_result(self):
        self.install_fake_gh_for_threads([])

        first = self.run_cmd([sys.executable, str(CLI_PY), "review", self.repo, self.pr])
        self.assertEqual(first.returncode, 6)

        synced = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "findings",
                self.repo,
                self.pr,
                "--input",
                "-",
                "--sync",
                "--source",
                "code-review",
            ],
            stdin=json.dumps(
                [
                    {
                        "title": "Missing guard",
                        "body": "The producer found a blocking issue.",
                        "path": "src/example.py",
                        "line": 12,
                        "severity": "P2",
                        "category": "correctness",
                    }
                ]
            )
            + "\n",
        )
        self.assertEqual(synced.returncode, 5, synced.stderr)

        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        producer_result = session["handoff"]["producer_results"]["code-review"]
        self.assertEqual(producer_result["status"], "submitted")
        self.assertEqual(producer_result["findings_count"], 1)

        second = self.run_cmd([sys.executable, str(CLI_PY), "review", self.repo, self.pr])
        self.assertEqual(second.returncode, 5, second.stderr)
        second_summary = json.loads(second.stdout)
        self.assertEqual(second_summary["status"], "BLOCKED")
        self.assertEqual(second_summary["reason_code"], "WAITING_FOR_FIX")
        self.assertEqual(second_summary["item_kind"], "local_finding")

    def test_cli_review_auto_converts_handoff_finding_blocks(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        (self.workspace_dir() / "incoming-findings.md").write_text(
            """```finding
title: Missing null guard
path: src/example.py
line: 12
body: Potential null dereference.
```
""",
            encoding="utf-8",
        )

        result = self.run_cmd([sys.executable, str(CLI_PY), "review", self.repo, self.pr])
        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "WAITING_FOR_FIX")
        self.assertEqual(summary["item_kind"], "local_finding")
        self.assertNotIn("scripts/cli.py", summary["next_action"])
        request = json.loads(Path(summary["artifact_path"]).read_text(encoding="utf-8"))
        self.assertEqual(request["resume_command"], f"gh-address-cr review {self.repo} {self.pr}")
        self.assertNotIn("scripts/cli.py", json.dumps(request))

    def test_cli_review_rerun_does_not_reingest_consumed_handoff(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        (self.workspace_dir() / "incoming-findings.json").write_text(
            json.dumps(
                [
                    {
                        "title": "Missing guard",
                        "body": "Fix the unsafe access.",
                        "path": "src/example.py",
                        "line": 12,
                        "severity": "P2",
                        "category": "correctness",
                    }
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        first = self.run_cmd([sys.executable, str(CLI_PY), "review", self.repo, self.pr])
        self.assertEqual(first.returncode, 5, first.stderr)
        first_summary = json.loads(first.stdout)
        self.assertEqual(first_summary["status"], "BLOCKED")

        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        item_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")
        item = session["items"][item_id]
        item["status"] = "CLOSED"
        item["state"] = "fixed"
        item["blocking"] = False
        item["handled"] = True
        item["validation_evidence"] = [{"command": "manual fixture", "result": "passed"}]
        self.session_file().write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")

        second = self.run_cmd([sys.executable, str(CLI_PY), "review", self.repo, self.pr])
        self.assertEqual(second.returncode, 0, second.stderr)
        second_summary = json.loads(second.stdout)
        self.assertEqual(second_summary["status"], "PASSED")

        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        item = session["items"][item_id]
        self.assertEqual(item["status"], "CLOSED")
        self.assertFalse(item["blocking"])

    def test_cli_review_rejects_invalid_handoff_markdown(self):
        gh = self.bin_dir / "gh"
        gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        gh.chmod(0o755)
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        (self.workspace_dir() / "incoming-findings.md").write_text("# narrative review only\n", encoding="utf-8")

        result = self.run_cmd([sys.executable, str(CLI_PY), "review", self.repo, self.pr])
        self.assertEqual(result.returncode, 2)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "FAILED")
        self.assertEqual(summary["reason_code"], "INVALID_PRODUCER_OUTPUT")
        self.assertEqual(summary["waiting_on"], "external_review_output")
        self.assertIn("fixed `finding` blocks", summary["next_action"])
        self.assertIn("fixed `finding` blocks", result.stderr)

    def test_cli_findings_machine_reports_pause_summary(self):
        payload_file = Path(self.temp_dir.name) / "findings.json"
        payload_file.write_text(
            json.dumps(
                [
                    {
                        "title": "Machine finding",
                        "body": "Needs a local fix.",
                        "path": "src/machine.py",
                        "line": 12,
                        "severity": "P2",
                        "category": "correctness",
                    }
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "--machine",
                "findings",
                self.repo,
                self.pr,
                "--input",
                str(payload_file),
            ]
        )
        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(
            set(summary),
            {
                "artifact_path",
                "commands",
                "counts",
                "exit_code",
                "gate_scope",
                "item_id",
                "item_kind",
                "next_action",
                "pr_number",
                "reason_code",
                "repo",
                "status",
                "waiting_on",
            },
        )
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["exit_code"], 5)
        self.assertGreaterEqual(summary["counts"]["blocking_items_count"], 1)
        self.assertEqual(summary["item_kind"], "local_finding")
        self.assertTrue(summary["item_id"].startswith("local-finding:"))
        self.assertIn("loop-request-", summary["artifact_path"])
        self.assertIn("Address the finding by running", summary["next_action"])
        self.assertNotIn("scripts/cli.py", summary["next_action"])
        request = json.loads(Path(summary["artifact_path"]).read_text(encoding="utf-8"))
        self.assertEqual(request["resume_command"], f"gh-address-cr findings {self.repo} {self.pr}")
        self.assertNotIn("scripts/cli.py", json.dumps(request))
        self.assertEqual(summary["reason_code"], "WAITING_FOR_FIX")
        self.assertEqual(summary["waiting_on"], "human_fix")

    def test_cli_threads_defaults_to_structured_summary(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "threads", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["item_id"], None)
        self.assertEqual(summary["item_kind"], None)
        self.assertEqual(summary["next_action"], "No action required.")
        self.assertEqual(summary["counts"]["blocking_items_count"], 0)
        self.assertEqual(summary["reason_code"], "PASSED")
        self.assertIsNone(summary["waiting_on"])

    def test_cli_threads_machine_emits_pass_summary(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "--machine", "threads", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["item_id"], None)
        self.assertEqual(summary["item_kind"], None)
        self.assertEqual(summary["next_action"], "No action required.")
        self.assertEqual(summary["counts"]["blocking_items_count"], 0)
        self.assertEqual(summary["reason_code"], "PASSED")
        self.assertIsNone(summary["waiting_on"])

    def test_cli_threads_machine_includes_actionable_thread_rows(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'THREAD_ACTIONABLE',
                            'isResolved': False,
                            'isOutdated': False,
                            'path': 'src/thread.py',
                            'line': 12,
                            'comments': {'nodes': [
                                {'url': 'https://example.test/thread/actionable', 'body': 'Please fix this.', 'author': {'login': 'reviewer'}},
                            ]},
                            'firstComment': {'nodes': [{'url': 'https://example.test/thread/actionable', 'body': 'Please fix this.'}]},
                            'latestComment': {'nodes': [{'url': 'https://example.test/thread/actionable', 'body': 'Please fix this.'}]},
                        }]
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "--machine", "threads", self.repo, self.pr])

        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["threads"][0]["item_id"], "github-thread:THREAD_ACTIONABLE")
        self.assertEqual(summary["threads"][0]["thread_id"], "THREAD_ACTIONABLE")
        self.assertEqual(summary["threads"][0]["path"], "src/thread.py")
        self.assertEqual(summary["threads"][0]["line"], 12)
        self.assertEqual(summary["threads"][0]["body"], "Please fix this.")
        self.assertEqual(summary["threads"][0]["url"], "https://example.test/thread/actionable")
        self.assertEqual(summary["threads"][0]["state"], "open")
        self.assertEqual(summary["threads"][0]["status"], "OPEN")
        self.assertFalse(summary["threads"][0]["is_resolved"])
        self.assertFalse(summary["threads"][0]["is_outdated"])
        self.assertFalse(summary["threads"][0]["accepted_response_present"])
        self.assertIsNone(summary["threads"][0]["reply_evidence"])

    def test_cli_findings_defaults_to_structured_summary(self):
        payload_file = Path(self.temp_dir.name) / "findings.json"
        payload_file.write_text(
            json.dumps(
                [
                    {
                        "title": "Alias finding",
                        "body": "Loop through the high-level findings alias.",
                        "path": "src/alias.py",
                        "line": 7,
                    }
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "findings",
                self.repo,
                self.pr,
                "--input",
                str(payload_file),
            ]
        )
        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["exit_code"], 5)
        self.assertEqual(summary["item_kind"], "local_finding")
        self.assertTrue(summary["item_id"].startswith("local-finding:"))
        self.assertIn("Address the finding by running", summary["next_action"])
        self.assertNotIn("scripts/cli.py", summary["next_action"])
        request = json.loads(Path(summary["artifact_path"]).read_text(encoding="utf-8"))
        self.assertEqual(request["resume_command"], f"gh-address-cr findings {self.repo} {self.pr}")
        self.assertNotIn("scripts/cli.py", json.dumps(request))
        self.assertEqual(summary["reason_code"], "WAITING_FOR_FIX")
        self.assertEqual(summary["waiting_on"], "human_fix")

    def test_cli_findings_alias_requires_findings_input(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "findings", self.repo, self.pr])
        self.assertNotEqual(result.returncode, 0)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "FAILED")
        self.assertEqual(summary["reason_code"], "MISSING_FINDINGS_INPUT")
        self.assertEqual(summary["waiting_on"], "findings_input")
        self.assertIn("--input", summary["next_action"])
        self.assertIn("does not generate findings", summary["next_action"])
        self.assertNotIn("scripts/cli.py", summary["next_action"])

    def test_cli_adapter_defaults_to_structured_summary(self):
        adapter = Path(self.temp_dir.name) / "adapter.py"
        adapter.write_text("import json\nprint(json.dumps([]))\n", encoding="utf-8")

        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "adapter",
                self.repo,
                self.pr,
                sys.executable,
                str(adapter),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["item_id"], None)
        self.assertEqual(summary["item_kind"], None)
        self.assertEqual(summary["next_action"], "No action required.")
        self.assertEqual(summary["reason_code"], "PASSED")
        self.assertIsNone(summary["waiting_on"])

    def test_cli_adapter_preserves_child_machine_and_human_flags(self):
        seen_args = Path(self.temp_dir.name) / "adapter-args.json"
        adapter = Path(self.temp_dir.name) / "adapter.py"
        adapter.write_text(
            (
                "import json\n"
                "import sys\n"
                "from pathlib import Path\n"
                f"Path({str(seen_args)!r}).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
                "print(json.dumps([]))\n"
            ),
            encoding="utf-8",
        )

        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "adapter",
                self.repo,
                self.pr,
                sys.executable,
                str(adapter),
                "--human",
                "--machine",
                "--auto-simple",
                "--lean",
                "--summary",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(
            json.loads(seen_args.read_text(encoding="utf-8")),
            ["--human", "--machine", "--auto-simple", "--lean", "--summary"],
        )

    def test_cli_review_fails_fast_when_gh_is_missing(self):
        self.env["PATH"] = str(self.bin_dir)
        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "review",
                self.repo,
                self.pr,
                "--input",
                "-",
            ],
            stdin="[]",
        )
        self.assertNotEqual(result.returncode, 0)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "FAILED")
        self.assertEqual(summary["reason_code"], "GH_NOT_FOUND")
        self.assertEqual(summary["waiting_on"], "github_cli")
        self.assertIn("gh", result.stderr)

    def test_cli_address_api_network_failure_includes_github_diagnostics(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    'if [ "$1" = "auth" ]; then exit 0; fi',
                    'if [ "$1" = "api" ]; then echo "error connecting to api.github.com" >&2; exit 1; fi',
                    "exit 1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr])

        self.assertEqual(result.returncode, 5)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["reason_code"], "GITHUB_NETWORK_FAILED")
        self.assertEqual(summary["waiting_on"], "github_network")
        self.assertEqual(summary["diagnostics"]["stderr_category"], "network")
        self.assertEqual(summary["diagnostics"]["command"][:3], ["gh", "api", "graphql"])
        self.assertIn("api.github.com", summary["diagnostics"]["stderr_excerpt"])

    def test_findings_requires_explicit_source_for_sync(self):
        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "findings",
                self.repo,
                self.pr,
                "--sync",
                "--input",
                "-",
            ],
            stdin=json.dumps(
                [
                    {
                        "title": "Needs source",
                        "body": "Sync should not default to a shared namespace.",
                        "path": "src/source.py",
                        "line": 4,
                    }
                ]
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an explicit --source", result.stdout)

    def test_findings_rejects_blank_input_without_session_mutation(self):
        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "findings",
                self.repo,
                self.pr,
                "--source",
                "local-agent:test",
                "--input",
                "-",
            ],
            stdin=" \n\t",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Use [] for an explicit empty producer result", result.stdout)
        self.assertFalse(self.session_file().exists())

    def test_address_syncs_github_threads_through_native_cli(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['auth', 'status']:
    raise SystemExit(0)
if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'THREAD_CLI',
                            'isResolved': False,
                            'isOutdated': False,
                            'path': 'src/cli.py',
                            'line': 6,
                            'firstComment': {'nodes': [{'url': 'https://example.test/thread/cli', 'body': 'cli'}]},
                            'latestComment': {'nodes': [{'url': 'https://example.test/thread/cli', 'body': 'cli'}]},
                        }]
                    }
                }
            }
        }
    }))
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr, "--lean"])
        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["item_id"], "github-thread:THREAD_CLI")

    def test_findings_cli_lists_items_in_native_session(self):
        result = self.run_findings_ingest(
            [
                {
                    "title": "CLI list-items",
                    "body": "Ensure public CLI dispatches to native session storage.",
                    "path": "README.md",
                    "line": 12,
                    "severity": "P3",
                    "category": "docs",
                }
            ]
        )
        self.assertEqual(result.returncode, 5, result.stderr)
        item = self.local_items()[0]
        self.assertTrue(item["item_id"].startswith("local-finding:"))
        self.assertEqual(item["title"], "CLI list-items")

    def test_adapter_command_ingests_findings_through_native_cli(self):
        self.install_fake_gh_for_threads([])
        adapter = Path(self.temp_dir.name) / "adapter.py"
        adapter.write_text(
            "import json\nprint(json.dumps([{'title':'py-adapter','body':'body','path':'src/a.py','line':4}]))\n",
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "adapter",
                self.repo,
                self.pr,
                sys.executable,
                str(adapter),
            ]
        )
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual(self.local_items()[0]["title"], "py-adapter")

    def test_findings_cli_accepts_envelope_payload(self):
        result = self.run_findings_ingest(
            {
                "findings": [
                    {
                        "title": "Envelope finding",
                        "message": "Imported from another review tool.",
                        "file": "src/envelope.py",
                        "position": 9,
                        "severity": "P2",
                        "category": "correctness",
                    }
                ]
            },
            source="local-agent:external-review",
        )
        self.assertEqual(result.returncode, 5, result.stderr)
        item = self.local_items()[0]
        self.assertEqual(item["path"], "src/envelope.py")
        self.assertEqual(item["line"], 9)
        self.assertEqual(item["body"], "Imported from another review tool.")

    def test_findings_cli_accepts_ndjson(self):
        result = self.run_findings_ingest(
            json.dumps(
                {
                    "check": "null-guard",
                    "description": "Potential null dereference.",
                    "filename": "src/cli_ingest.py",
                    "line": 5,
                    "severity": "P1",
                }
            )
            + "\n",
            source="local-agent:cli-import",
        )
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual(self.local_items()[0]["path"], "src/cli_ingest.py")

    def test_legacy_control_plane_root_command_is_unsupported(self):
        result = self.run_runtime_module("control-plane", "remote", self.repo, self.pr)

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsupported legacy command: control-plane", result.stderr)
        self.assertFalse(self.session_file().exists())

    def test_native_address_replaces_control_plane_remote_bootstrap(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['auth', 'status']:
    raise SystemExit(0)
if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'THREAD_REMOTE',
                            'isResolved': False,
                            'isOutdated': False,
                            'path': 'src/remote.py',
                            'line': 3,
                            'firstComment': {'nodes': [{'url': 'https://example.test/thread/remote', 'body': 'remote'}]},
                            'latestComment': {'nodes': [{'url': 'https://example.test/thread/remote', 'body': 'remote'}]},
                        }]
                    }
                }
            }
        }
    }))
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr, "--lean"])
        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["item_id"], "github-thread:THREAD_REMOTE")

    def test_native_findings_replaces_control_plane_local_json_ingest(self):
        result = self.run_findings_ingest(
            [
                {
                    "title": "stdin bridge finding",
                    "body": "Imported through --input -.",
                    "path": "src/stdin_bridge.py",
                    "line": 14,
                    "severity": "P2",
                }
            ],
            source="local-agent:code-review",
        )
        self.assertEqual(result.returncode, 5, result.stderr)
        item = self.local_items()[0]
        self.assertEqual(item["title"], "stdin bridge finding")
        self.assertEqual(item["line"], 14)

    def test_native_adapter_replaces_control_plane_local_adapter(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['auth', 'status']:
    raise SystemExit(0)
if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
    raise SystemExit(0)
raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)
        adapter = Path(self.temp_dir.name) / "adapter.py"
        adapter.write_text(
            "import json\nprint(json.dumps([{'title':'adapter finding','body':'body','path':'src/a.py','line':4}]))\n",
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "adapter",
                self.repo,
                self.pr,
                sys.executable,
                str(adapter),
            ]
        )
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual(self.local_items()[0]["title"], "adapter finding")

    def test_review_to_findings_python_converts_markdown_blocks_to_workspace_json(self):
        markdown = """Intro text that should be ignored.

```finding
title: Missing null guard
path: src/example.py
line: 12
severity: P2
category: correctness
confidence: high
body:
Potential null dereference.
```

```finding
title: Another finding
path: src/other.py
line: 18
body: Inline body text.
```
"""
        result = self.run_cmd(
            [
                sys.executable,
                str(REVIEW_TO_FINDINGS_PY),
                "--input",
                "-",
                self.repo,
                self.pr,
            ],
            stdin=markdown,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        findings = json.loads(result.stdout)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["title"], "Missing null guard")
        self.assertEqual(findings[0]["path"], "src/example.py")
        self.assertEqual(findings[0]["line"], 12)
        self.assertEqual(findings[0]["body"], "Potential null dereference.")
        self.assertEqual(findings[1]["title"], "Another finding")
        self.assertEqual(findings[1]["body"], "Inline body text.")
        workspace_file = self.workspace_dir() / "code-review-findings.json"
        self.assertTrue(workspace_file.exists())
        persisted = json.loads(workspace_file.read_text(encoding="utf-8"))
        self.assertEqual(persisted, findings)

    def test_review_to_findings_python_rejects_missing_required_fields(self):
        markdown = """```finding
path: src/example.py
line: 12
body: Missing title should fail.
```
"""
        result = self.run_cmd(
            [
                sys.executable,
                str(REVIEW_TO_FINDINGS_PY),
                "--input",
                "-",
                self.repo,
                self.pr,
            ],
            stdin=markdown,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must include a title", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


    def test_cli_dispatches_review_to_findings(self):
        markdown = """```finding
title: CLI finding
path: src/cli.py
line: 5
body: CLI bridge output.
```
"""
        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "review-to-findings", "--input", "-", self.repo, self.pr],
            stdin=markdown,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        findings = json.loads(result.stdout)
        self.assertEqual(findings[0]["title"], "CLI finding")
        self.assertTrue((self.workspace_dir() / "code-review-findings.json").exists())

    def test_findings_cli_accepts_stdin_array(self):
        result = self.run_findings_ingest(
            [
                {
                    "title": "stdin finding",
                    "body": "Imported through stdin.",
                    "path": "src/stdin.py",
                    "line": 3,
                    "severity": "P3",
                    "category": "docs",
                }
            ],
            source="local-agent:stdin-review",
        )
        self.assertEqual(result.returncode, 5, result.stderr)
        item = self.local_items()[0]
        self.assertEqual(item["path"], "src/stdin.py")
        self.assertEqual(item["line"], 3)
        self.assertEqual(item["source"], "local-agent:stdin-review")

    def test_address_syncs_session_with_mocked_gh(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['auth', 'status']:
    raise SystemExit(0)
if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'THREAD_A',
                            'isResolved': False,
                            'isOutdated': False,
                            'path': 'src/a.py',
                            'line': 4,
                            'firstComment': {'nodes': [{'url': 'https://example.test/thread/A', 'body': 'Please fix'}]},
                            'latestComment': {'nodes': [{'url': 'https://example.test/thread/A', 'body': 'Please fix'}]},
                        }]
                    }
                }
            }
        }
    }))
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr, "--lean"])
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual(json.loads(result.stdout)["item_id"], "github-thread:THREAD_A")

    def test_address_lists_reopened_thread_as_unhandled(self):
        gh = self.bin_dir / "gh"
        phase_file = Path(self.temp_dir.name) / "thread_phase.txt"
        phase_file.write_text("resolved", encoding="utf-8")
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import pathlib
import sys

phase = pathlib.Path({str(phase_file)!r}).read_text(encoding='utf-8').strip()
node = {{
    'id': 'THREAD_REOPENED',
    'isResolved': phase == 'resolved',
    'isOutdated': False,
    'path': 'src/reopened.py',
    'line': 4,
    'firstComment': {{'nodes': [{{'url': 'https://example.test/thread/reopened', 'body': 'Please revisit this.'}}]}},
    'latestComment': {{'nodes': [{{'url': 'https://example.test/thread/reopened', 'body': 'Please revisit this.'}}]}},
}}

if sys.argv[1:3] == ['auth', 'status']:
    raise SystemExit(0)
if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({{
        'data': {{
            'repository': {{
                'pullRequest': {{
                    'reviewThreads': {{
                        'pageInfo': {{'hasNextPage': False, 'endCursor': None}},
                        'nodes': [node],
                    }}
                }}
            }}
        }}
    }}))
else:
    raise SystemExit(f'unhandled gh args: {{sys.argv[1:]}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        first = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr, "--lean"])
        self.assertEqual(first.returncode, 5, first.stderr)

        phase_file.write_text("reopened", encoding="utf-8")
        second = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr, "--lean"])
        self.assertEqual(second.returncode, 5, second.stderr)
        self.assertEqual(json.loads(second.stdout)["item_id"], "github-thread:THREAD_REOPENED")

    def test_address_lists_stale_thread_as_unhandled(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['auth', 'status']:
    raise SystemExit(0)
if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'THREAD_STALE',
                            'isResolved': False,
                            'isOutdated': True,
                            'path': 'src/stale.py',
                            'line': 9,
                            'firstComment': {'nodes': [{'url': 'https://example.test/thread/stale', 'body': 'Still needs handling.'}]},
                            'latestComment': {'nodes': [{'url': 'https://example.test/thread/stale', 'body': 'Still needs handling.'}]},
                        }]
                    }
                }
            }
        }
    }))
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "address", self.repo, self.pr, "--lean"])
        self.assertEqual(result.returncode, 5, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["item_id"], "github-thread:THREAD_STALE")
        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        self.assertEqual(session["items"]["github-thread:THREAD_STALE"]["state"], "stale")

    def test_final_gate_python_passes_on_resolved_threads(self):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        self.session_file().write_text(
            json.dumps(
                {
                    "repo": self.repo,
                    "pr_number": self.pr,
                    "status": "WAITING_FOR_GATE",
                    "items": {
                        "github-thread:THREAD_DONE": {
                            "item_id": "github-thread:THREAD_DONE",
                            "item_kind": "github_thread",
                            "thread_id": "THREAD_DONE",
                            "state": "closed",
                            "reply_evidence": {
                                "reply_url": "https://example.test/thread/done#reply",
                                "author_login": "agent-login",
                            },
                            "validation_evidence": [{"command": "python3 -m unittest tests.test_python_wrappers"}],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]

if args[:2] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'THREAD_DONE',
                            'isResolved': True,
                            'isOutdated': False,
                            'path': 'src/a.py',
                            'line': 4,
                            'comments': {'nodes': [
                                {'url': 'https://example.test/thread/done', 'body': 'Done', 'author': {'login': 'reviewer'}},
                                {'url': 'https://example.test/thread/done#reply', 'body': 'Handled', 'author': {'login': 'agent-login'}},
                            ]},
                            'firstComment': {'nodes': [{'url': 'https://example.test/thread/done', 'body': 'Done'}]},
                            'latestComment': {'nodes': [{'url': 'https://example.test/thread/done#reply', 'body': 'Handled'}]},
                        }]
                    }
                }
            }
        }
    }))
elif args[:2] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif args[:2] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "final-gate", "--human", "--no-auto-clean", "--audit-id", "gate-test", self.repo, self.pr]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("== Current Run Snapshot ==", result.stdout)
        self.assertNotIn("GitHub threads: total 1;", result.stdout)
        self.assertNotIn("Local findings: total 0;", result.stdout)
        self.assertIn("== Gate Result ==", result.stdout)
        self.assertIn("Verified: 0 Unresolved Threads found", result.stdout)
        self.assertIn("Verified: 0 Pending Reviews found", result.stdout)
        self.assertIn("Session blocking items: 0", result.stdout)
        self.assertIn("== Machine Gate Diagnostics ==", result.stdout)
        self.assertIn("unresolved_github_threads_count=0", result.stdout)
        self.assertIn("unresolved_remote_threads_count=0", result.stdout)
        self.assertIn("blocking_items_count=0", result.stdout)
        self.assertIn("blocking_local_items_count=0", result.stdout)
        self.assertIn("blocking_github_items_count=0", result.stdout)
        self.assertIn("github_threads_missing_reply_count=0", result.stdout)
        self.assertIn("missing_validation_evidence_count=0", result.stdout)
        self.assertIn("pending_current_login_review_count=0", result.stdout)
        summary_file = self.workspace_dir() / "audit_summary.md"
        self.assertTrue(summary_file.exists())
        self.assertIn("== Agent Efficiency Summary ==", result.stdout)
        self.assertIn("telemetry_coverage_label=unavailable", result.stdout)
        self.assertIn("Efficiency report path:", result.stdout)
        self.assertIn("== PR Completion Summary Guidance ==", result.stdout)
        self.assertIn(
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: unavailable/low (0 events, 0.0%) | sources: telemetry 0 | duration: no observed duration | slowest: none | issues: none]",
            result.stdout,
        )
        summary_text = summary_file.read_text(encoding="utf-8")
        self.assertIn("- telemetry_coverage_label: unavailable", summary_text)
        self.assertIn("- efficiency_report_path:", summary_text)
        self.assertIn("- telemetry_sources: telemetry (runtime): 0 events, unavailable", summary_text)
        self.assertIn("- telemetry_diagnostics: none", summary_text)
        self.assertIn("## PR Completion Summary Guidance", summary_text)
        self.assertIn(
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: unavailable/low (0 events, 0.0%) | sources: telemetry 0 | duration: no observed duration | slowest: none | issues: none]",
            summary_text,
        )
        report_path_line = next(line for line in summary_text.splitlines() if line.startswith("- efficiency_report_path:"))
        report_path = Path(report_path_line.partition(": ")[2])
        self.assertTrue(report_path.exists())

    def test_cli_telemetry_ingest_and_summary_contract(self):
        payload = json.dumps(
            {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "run unit tests",
                "duration_ms": 89105,
                "status": "success",
                "metadata": {"command_label": "python3 -m unittest discover -s tests", "exit_code": 0},
            }
        )
        feed = Path(self.temp_dir.name) / "agent-telemetry.jsonl"
        feed.write_text(payload + "\n", encoding="utf-8")

        ingest = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                self.repo,
                self.pr,
                "--source",
                "generic-agent",
                "--format",
                "agent-jsonl",
                "--input",
                str(feed),
            ]
        )
        self.assertEqual(ingest.returncode, 0, ingest.stderr)
        ingest_summary = json.loads(ingest.stdout)
        self.assertEqual(ingest_summary["status"], "SUCCESS")
        self.assertEqual(ingest_summary["reason_code"], "TELEMETRY_IMPORTED")
        self.assertEqual(ingest_summary["accepted_count"], 1)
        self.assertEqual(ingest_summary["duplicate_count"], 0)
        self.assertEqual(len(ingest_summary["accepted_fingerprints"]), 1)
        self.assertEqual(ingest_summary["duplicate_fingerprints"], [])

        duplicate = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                self.repo,
                self.pr,
                "--source",
                "generic-agent",
                "--format",
                "agent-jsonl",
                "--input",
                str(feed),
            ]
        )
        self.assertNotEqual(duplicate.returncode, 0)
        duplicate_summary = json.loads(duplicate.stdout)
        self.assertEqual(duplicate_summary["reason_code"], "DUPLICATE_TELEMETRY_IMPORT")
        self.assertEqual(duplicate_summary["accepted_fingerprints"], [])
        self.assertEqual(duplicate_summary["duplicate_fingerprints"], ingest_summary["accepted_fingerprints"])

        summary = self.run_cmd([sys.executable, str(CLI_PY), "telemetry", "summary", self.repo, self.pr])
        self.assertEqual(summary.returncode, 0, summary.stderr)
        report = json.loads(summary.stdout)
        self.assertEqual(report["status"], "SUCCESS")
        self.assertEqual(report["coverage_label"], "partial")
        self.assertEqual(report["total_events"], 1)
        self.assertEqual(report["diagnostics"], [])
        self.assertEqual(report["slowest_operations"][0]["operation"], "run unit tests")

        markdown = self.run_cmd(
            [sys.executable, str(CLI_PY), "telemetry", "summary", self.repo, self.pr, "--format", "markdown"]
        )
        self.assertEqual(markdown.returncode, 0, markdown.stderr)
        self.assertIn("## Agent Efficiency Summary", markdown.stdout)
        self.assertIn("coverage_label: partial", markdown.stdout)

    def test_cli_telemetry_rejects_unsafe_feed_without_session_mutation(self):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        self.session_file().write_text(json.dumps({"status": "OPEN", "items": {}}), encoding="utf-8")
        before = self.session_file().read_text(encoding="utf-8")
        feed = Path(self.temp_dir.name) / "unsafe.jsonl"
        feed.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "e1",
                    "kind": "tool_call",
                    "operation": "unsafe",
                    "duration_ms": 1,
                    "status": "success",
                    "metadata": {"token": "ghp_secret", "raw_prompt": "secret prompt"},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                self.repo,
                self.pr,
                "--source",
                "generic-agent",
                "--format",
                "agent-jsonl",
                "--input",
                str(feed),
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
        self.assertEqual(self.session_file().read_text(encoding="utf-8"), before)

    def test_cli_telemetry_rejects_unsupported_format(self):
        feed = Path(self.temp_dir.name) / "agent-telemetry.txt"
        feed.write_text("", encoding="utf-8")

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                self.repo,
                self.pr,
                "--source",
                "generic-agent",
                "--format",
                "xml",
                "--input",
                str(feed),
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "UNSUPPORTED_TELEMETRY_FORMAT")

    def test_cli_telemetry_ingest_unavailable_input_keeps_machine_contract_fields(self):
        missing_feed = Path(self.temp_dir.name) / "missing.jsonl"

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                self.repo,
                self.pr,
                "--source",
                "generic-agent",
                "--format",
                "agent-jsonl",
                "--input",
                str(missing_feed),
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "TELEMETRY_INPUT_UNAVAILABLE")
        self.assertEqual(payload["accepted_fingerprints"], [])
        self.assertEqual(payload["duplicate_fingerprints"], [])
        self.assertEqual(payload["diagnostics"], ["telemetry input unavailable"])
        self.assertNotIn(str(missing_feed), result.stdout)
        import_lines = (self.workspace_dir() / "telemetry-imports.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(import_lines), 1)
        self.assertEqual(json.loads(import_lines[0])["reason_code"], "TELEMETRY_INPUT_UNAVAILABLE")

    def test_cli_telemetry_ingest_unavailable_input_redacts_unsafe_source(self):
        missing_feed = Path(self.temp_dir.name) / "missing.jsonl"

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                self.repo,
                self.pr,
                "--source",
                "/home/alice/agent",
                "--format",
                "agent-jsonl",
                "--input",
                str(missing_feed),
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "TELEMETRY_INPUT_UNAVAILABLE")
        self.assertEqual(payload["source"], "[redacted]")
        self.assertNotIn("/home/alice", result.stdout)

    def test_cli_telemetry_ingest_unavailable_input_redacts_control_character_source(self):
        missing_feed = Path(self.temp_dir.name) / "missing.jsonl"

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                self.repo,
                self.pr,
                "--source",
                "generic\n- injected",
                "--format",
                "agent-jsonl",
                "--input",
                str(missing_feed),
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "TELEMETRY_INPUT_UNAVAILABLE")
        self.assertEqual(payload["source"], "[redacted]")
        import_lines = (self.workspace_dir() / "telemetry-imports.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(import_lines[0])["source"], "[redacted]")

    def test_cli_telemetry_ingest_unavailable_input_redacts_unsafe_format(self):
        missing_feed = Path(self.temp_dir.name) / "missing.jsonl"

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                self.repo,
                self.pr,
                "--source",
                "generic-agent",
                "--format",
                "ghp_secret_format",
                "--input",
                str(missing_feed),
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "TELEMETRY_INPUT_UNAVAILABLE")
        self.assertEqual(payload["format"], "[redacted]")
        self.assertNotIn("ghp_secret_format", result.stdout)
        self.assertEqual(payload["diagnostics"], ["telemetry input unavailable"])

    def test_cli_telemetry_ingest_unavailable_input_redacts_private_source_identifier(self):
        missing_feed = Path(self.temp_dir.name) / "missing.jsonl"

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                self.repo,
                self.pr,
                "--source",
                "username-alice-laptop",
                "--format",
                "agent-jsonl",
                "--input",
                str(missing_feed),
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "TELEMETRY_INPUT_UNAVAILABLE")
        self.assertEqual(payload["source"], "[redacted]")
        self.assertNotIn("username-alice-laptop", result.stdout)

    def test_cli_telemetry_ingest_unavailable_input_keeps_safe_sk_substring_source(self):
        missing_feed = Path(self.temp_dir.name) / "missing.jsonl"

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "telemetry",
                "ingest",
                self.repo,
                self.pr,
                "--source",
                "disk-usage-agent",
                "--format",
                "agent-jsonl",
                "--input",
                str(missing_feed),
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "TELEMETRY_INPUT_UNAVAILABLE")
        self.assertEqual(payload["source"], "disk-usage-agent")

    def test_cli_telemetry_summary_fails_loud_when_external_telemetry_is_corrupted(self):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        (self.workspace_dir() / "external-telemetry.jsonl").write_text("{not-json}\n", encoding="utf-8")

        result = self.run_cmd([sys.executable, str(CLI_PY), "telemetry", "summary", self.repo, self.pr])

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "TELEMETRY_REPORT_UNAVAILABLE")
        self.assertTrue(any("external telemetry line 1" in diagnostic for diagnostic in payload["diagnostics"]))
        artifact = json.loads(Path(payload["report_artifact"]).read_text(encoding="utf-8"))
        self.assertEqual(artifact["status"], "FAILED")
        self.assertEqual(artifact["reason_code"], "TELEMETRY_REPORT_UNAVAILABLE")

    def test_cli_telemetry_summary_fails_loud_when_external_store_is_non_file(self):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        (self.workspace_dir() / "external-telemetry.jsonl").mkdir()

        result = self.run_cmd([sys.executable, str(CLI_PY), "telemetry", "summary", self.repo, self.pr])

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "TELEMETRY_REPORT_UNAVAILABLE")
        self.assertTrue(any("external telemetry store is not a regular file" in item for item in payload["diagnostics"]))

    def test_cli_telemetry_summary_fails_loud_when_import_ledger_is_corrupted(self):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        (self.workspace_dir() / "telemetry-imports.jsonl").write_text("{not-json}\n", encoding="utf-8")

        result = self.run_cmd([sys.executable, str(CLI_PY), "telemetry", "summary", self.repo, self.pr])

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "TELEMETRY_REPORT_UNAVAILABLE")
        self.assertTrue(any("telemetry import summary line 1" in item for item in payload["diagnostics"]))

    def test_cli_telemetry_summary_fails_loud_when_import_ledger_is_non_file(self):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        (self.workspace_dir() / "telemetry-imports.jsonl").mkdir()

        result = self.run_cmd([sys.executable, str(CLI_PY), "telemetry", "summary", self.repo, self.pr])

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "TELEMETRY_REPORT_UNAVAILABLE")
        self.assertTrue(any("telemetry import summary is not a regular file" in item for item in payload["diagnostics"]))

    def test_cli_telemetry_summary_fails_loud_when_import_diagnostics_shape_is_corrupted(self):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        (self.workspace_dir() / "telemetry-imports.jsonl").write_text(
            json.dumps({"status": "FAILED", "source": "agent", "diagnostics": 5}) + "\n",
            encoding="utf-8",
        )

        result = self.run_cmd([sys.executable, str(CLI_PY), "telemetry", "summary", self.repo, self.pr])

        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "TELEMETRY_REPORT_UNAVAILABLE")
        self.assertTrue(any("diagnostics must be a list" in item for item in payload["diagnostics"]))

    def test_cli_telemetry_summary_treats_report_artifact_write_failure_as_unavailable(self):
        from gh_address_cr.commands.telemetry import telemetry_report_has_storage_diagnostics

        self.assertTrue(
            telemetry_report_has_storage_diagnostics(
                {
                    "diagnostics": [
                        "efficiency report artifact unavailable: OSError: disk full",
                        "telemetry import summary line 1: invalid JSON: Expecting property name",
                        "telemetry import summary line 2: record must be a JSON object",
                    ]
                }
            )
        )

    def test_final_gate_fail_open_when_external_telemetry_is_corrupted(self):
        self.install_fake_gh_for_threads([])
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        (self.workspace_dir() / "external-telemetry.jsonl").write_text("{not-json}\n", encoding="utf-8")

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "final-gate", "--human", "--no-auto-clean", "--audit-id", "corrupted-telemetry", self.repo, self.pr]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("== Agent Efficiency Summary ==", result.stdout)
        self.assertIn("telemetry_coverage_label=unavailable", result.stdout)
        self.assertIn("telemetry_sources=telemetry (runtime): 0 events, unavailable", result.stdout)
        self.assertIn("telemetry_diagnostics=external telemetry line 1: invalid JSON", result.stdout)
        summary_file = self.workspace_dir() / "audit_summary.md"
        summary_text = summary_file.read_text(encoding="utf-8")
        self.assertIn("- telemetry_sources: telemetry (runtime): 0 events, unavailable", summary_text)
        self.assertIn("- telemetry_diagnostics: external telemetry line 1: invalid JSON", summary_text)
        report_path_line = next(line for line in summary_text.splitlines() if line.startswith("- efficiency_report_path:"))
        report = json.loads(Path(report_path_line.partition(": ")[2]).read_text(encoding="utf-8"))
        self.assertTrue(any("external telemetry line 1" in diagnostic for diagnostic in report["diagnostics"]))

    def test_final_gate_imports_host_telemetry_from_environment_hook(self):
        self.install_fake_gh_for_threads([])
        feed = Path(self.temp_dir.name) / "host-telemetry.jsonl"
        feed.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "source": "assistant-host",
                    "source_session_id": "session-77",
                    "event_id": "tool-1",
                    "kind": "tool_call",
                    "operation": "inspect issue",
                    "duration_ms": 1250,
                    "status": "success",
                    "metadata": {"tool": "gh issue view"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.env["GH_ADDRESS_CR_HOST_TELEMETRY_INPUT"] = str(feed)
        self.env["GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE"] = "assistant-host"

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "final-gate", "--human", "--no-auto-clean", "--audit-id", "host-telemetry", self.repo, self.pr]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("telemetry_coverage_label=partial", result.stdout)
        self.assertIn("telemetry_sources=assistant-host (host-adapter): 1 events, available", result.stdout)
        self.assertIn("telemetry_diagnostics=none", result.stdout)
        summary_text = self.audit_summary_file().read_text(encoding="utf-8")
        self.assertIn("- telemetry_coverage_label: partial", summary_text)
        self.assertIn("- telemetry_sources: assistant-host (host-adapter): 1 events, available", summary_text)
        report_path_line = next(line for line in summary_text.splitlines() if line.startswith("- efficiency_report_path:"))
        report = json.loads(Path(report_path_line.partition(": ")[2]).read_text(encoding="utf-8"))
        self.assertEqual(report["total_events"], 1)
        self.assertEqual(report["slowest_operations"][0]["operation"], "inspect issue")
        self.assertEqual(report["sources"][0]["source"], "assistant-host")

    def test_final_gate_host_telemetry_hook_missing_input_is_fail_open(self):
        self.install_fake_gh_for_threads([])
        self.env["GH_ADDRESS_CR_HOST_TELEMETRY_INPUT"] = str(Path(self.temp_dir.name) / "missing-host-telemetry.jsonl")
        self.env["GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE"] = "assistant-host"

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "final-gate", "--human", "--no-auto-clean", "--audit-id", "missing-host-telemetry", self.repo, self.pr]
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("telemetry_coverage_label=unavailable", result.stdout)
        self.assertIn("telemetry_diagnostics=telemetry import assistant-host: telemetry input unavailable", result.stdout)
        summary_text = self.audit_summary_file().read_text(encoding="utf-8")
        self.assertIn("- telemetry_coverage_label: unavailable", summary_text)
        self.assertIn("- telemetry_diagnostics: telemetry import assistant-host: telemetry input unavailable", summary_text)
        report_path_line = next(line for line in summary_text.splitlines() if line.startswith("- efficiency_report_path:"))
        report = json.loads(Path(report_path_line.partition(": ")[2]).read_text(encoding="utf-8"))
        self.assertEqual(report["total_events"], 0)
        self.assertIn("telemetry import assistant-host: telemetry input unavailable", report["diagnostics"])

    def test_final_gate_python_fails_on_resolved_thread_without_viewer_reply(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]

if args[:2] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'THREAD_DONE',
                            'isResolved': True,
                            'isOutdated': False,
                            'path': 'src/a.py',
                            'line': 4,
                            'comments': {'nodes': [
                                {'url': 'https://example.test/thread/done', 'body': 'Done', 'author': {'login': 'reviewer'}},
                            ]},
                            'firstComment': {'nodes': [{'url': 'https://example.test/thread/done', 'body': 'Done'}]},
                            'latestComment': {'nodes': [{'url': 'https://example.test/thread/done', 'body': 'Done'}]},
                        }]
                    }
                }
            }
        }
    }))
elif args[:2] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif args[:2] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "final-gate", "--human", "--no-auto-clean", self.repo, self.pr])
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("github_threads_missing_reply_count=1", result.stdout)
        self.assertIn("missing reply evidence", result.stderr)

    def test_cli_final_gate_no_auto_clean_preserves_audit_report_artifacts(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]

if args[:2] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif args[:2] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif args[:2] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "final-gate", "--human", "--no-auto-clean", "--audit-id", "native-run", self.repo, self.pr]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Audit summary path:", result.stdout)
        self.assertIn("Audit summary sha256:", result.stdout)

    def test_final_gate_python_fails_when_current_login_has_pending_reviews(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:2] == ['api', 'graphql']:
    print(json.dumps({{
        'data': {{
            'repository': {{
                'pullRequest': {{
                    'reviewThreads': {{
                        'pageInfo': {{'hasNextPage': False, 'endCursor': None}},
                        'nodes': [{{
                            'id': 'THREAD_DONE',
                            'isResolved': True,
                            'isOutdated': False,
                            'path': 'src/a.py',
                            'line': 4,
                            'comments': {{'nodes': [
                                {{'url': 'https://example.test/thread/done', 'body': 'Done', 'author': {{'login': 'reviewer'}}}},
                                {{'url': 'https://example.test/thread/done#reply', 'body': 'Handled', 'author': {{'login': 'agent-login'}}}},
                            ]}},
                            'firstComment': {{'nodes': [{{'url': 'https://example.test/thread/done', 'body': 'Done'}}]}},
                            'latestComment': {{'nodes': [{{'url': 'https://example.test/thread/done#reply', 'body': 'Handled'}}]}},
                        }}]
                    }}
                }}
            }}
        }}
    }}))
elif args[:2] == ['api', 'user']:
    print(json.dumps({{'login': 'agent-login'}}))
elif args[:2] == ['api', 'repos/{self.repo}/pulls/{self.pr}/reviews?per_page=100&page=1']:
    print(json.dumps([{{
        'state': 'PENDING',
        'node_id': 'PENDING_REVIEW_1',
        'user': {{'login': 'agent-login'}},
    }}]))
elif args[:2] == ['api', 'repos/{self.repo}/pulls/{self.pr}/reviews?per_page=100&page=2']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "final-gate", "--human", "--no-auto-clean", self.repo, self.pr])
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("Pending review count: 1", result.stdout)
        self.assertIn("pending review(s)", result.stderr)


    def test_cli_machine_rejects_unsupported_subcommand_before_running_it(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "--machine", "review-to-findings", self.repo, self.pr])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--machine and --human are only supported for", result.stderr)
        self.assertFalse(self.workspace_dir().exists())

    def test_cli_output_flags_reject_utility_commands_before_running_them(self):
        for command in ("review-to-findings", "submit-feedback"):
            with self.subTest(command=command):
                result = self.run_cmd([sys.executable, str(CLI_PY), "--machine", command, "--help"])

                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("--machine and --human are only supported for", result.stderr)
                self.assertFalse(self.workspace_dir().exists())

    def test_final_gate_failure_message_reports_actual_failure_reasons(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        ingest = self.run_findings_ingest(
            [
                {
                    "title": "Blocking finding",
                    "body": "Still open.",
                    "path": "src/blocking.py",
                    "line": 3,
                    "severity": "P2",
                    "category": "correctness",
                }
            ]
        )
        self.assertEqual(ingest.returncode, 5, ingest.stderr)

        result = self.run_cmd([sys.executable, str(CLI_PY), "final-gate", "--human", "--no-auto-clean", self.repo, self.pr])
        self.assertNotEqual(result.returncode, 0)
        audit_lines = self.audit_log_file().read_text(encoding="utf-8").splitlines()
        last = json.loads(audit_lines[-1])
        self.assertEqual(last["status"], "failed")
        self.assertEqual(last["message"], "Gate failed; 1 blocking item(s) remain")

    def test_final_gate_auto_clean_does_not_recreate_workspace(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "final-gate", "--human", "--auto-clean", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.workspace_dir().exists())

    def test_final_gate_auto_clean_archives_workspace_before_deleting_it(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "final-gate", "--human", "--auto-clean", "--audit-id", "archive-run", self.repo, self.pr]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.workspace_dir().exists())
        self.assertTrue(self.archive_root().exists())

        archived_runs = sorted(self.archive_root().iterdir())
        self.assertEqual(len(archived_runs), 1)
        archived_workspace = archived_runs[0]
        archived_summary = archived_workspace / "audit_summary.md"
        archived_report = archived_workspace / "efficiency-report.json"
        self.assertTrue((archived_workspace / "audit.jsonl").exists())
        self.assertTrue((archived_workspace / "trace.jsonl").exists())
        self.assertTrue(archived_summary.exists())
        self.assertTrue(archived_report.exists())
        self.assertTrue((archived_workspace / "session.json").exists())
        self.assertIn(f"Audit summary path: {archived_summary}", result.stdout)
        self.assertIn("Audit summary sha256:", result.stdout)
        summary_text = archived_summary.read_text(encoding="utf-8")
        self.assertIn(f"- efficiency_report_path: {archived_report}", summary_text)
        self.assertIn("## PR Completion Summary Guidance", summary_text)
        self.assertIn(f"- Efficiency Report: {archived_report}", summary_text)
        self.assertIn(f"- Audit Summary: {archived_summary}", summary_text)
        report = json.loads(archived_report.read_text(encoding="utf-8"))
        self.assertEqual(report["report_artifact"], str(archived_report))

        trace_lines = (archived_workspace / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(trace_lines)
        trace_entries = [json.loads(line) for line in trace_lines if line.strip()]
        self.assertTrue(any(entry.get("run_id") == "archive-run" for entry in trace_entries))
        self.assertTrue(all(str(self.workspace_dir()) not in json.dumps(entry) for entry in trace_entries))
        self.assertTrue(any(entry.get("efficiency_report_path") == str(archived_report) for entry in trace_entries))

        audit_entries = [
            json.loads(line)
            for line in (archived_workspace / "audit.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        archived_summary_sha256 = hashlib.sha256(archived_summary.read_bytes()).hexdigest()
        self.assertTrue(all(str(self.workspace_dir()) not in json.dumps(entry) for entry in audit_entries))
        self.assertTrue(any(entry.get("details", {}).get("summary_file") == str(archived_summary) for entry in audit_entries))
        self.assertTrue(
            any(entry.get("details", {}).get("summary_sha256") == archived_summary_sha256 for entry in audit_entries)
        )
        self.assertTrue(
            any(
                entry.get("details", {}).get("efficiency_report", {}).get("report_artifact") == str(archived_report)
                for entry in audit_entries
            )
        )

    def test_final_gate_auto_clean_archives_in_memory_efficiency_report_when_artifact_write_fails(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'repository': {
                'pullRequest': {
                    'reviewThreads': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': []
                    }
                }
            }
        }
    }))
elif sys.argv[1:3] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif sys.argv[1:3] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        report_artifact = self.workspace_dir() / "efficiency-report.json"
        report_artifact.mkdir(parents=True)

        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "final-gate", "--human", "--auto-clean", "--audit-id", "artifact-fail", self.repo, self.pr]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.workspace_dir().exists())

        archived_workspace = self.archive_root() / "artifact-fail"
        archived_summary = archived_workspace / "audit_summary.md"
        archived_report = archived_workspace / "efficiency-report.json"
        self.assertTrue(archived_summary.exists())
        self.assertTrue(archived_report.is_file())
        self.assertIn(f"Efficiency report path: {archived_report}", result.stdout)

        summary_text = archived_summary.read_text(encoding="utf-8")
        self.assertIn(f"- efficiency_report_path: {archived_report}", summary_text)
        report = json.loads(archived_report.read_text(encoding="utf-8"))
        self.assertEqual(report["report_artifact"], str(archived_report))
        self.assertTrue(
            any("efficiency report artifact unavailable" in diagnostic for diagnostic in report["diagnostics"])
        )

        audit_entries = [
            json.loads(line)
            for line in (archived_workspace / "audit.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(all(str(self.workspace_dir()) not in json.dumps(entry) for entry in audit_entries))
        self.assertTrue(
            any(
                entry.get("details", {}).get("efficiency_report", {}).get("report_artifact") == str(archived_report)
                for entry in audit_entries
            )
        )

    def test_mark_handled_requires_explicit_repo_and_pr(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:3] == ['repo', 'view', '--json']:
    print(json.dumps({'nameWithOwner': 'octo/example'}))
elif args[:3] == ['pr', 'view', '--json']:
    print(json.dumps({'number': 77}))
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CLI_PY), "mark-handled", "THREAD_NEEDS_CONTEXT"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported legacy command: mark-handled", result.stderr)
