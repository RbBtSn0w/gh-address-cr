import json
import sys
from pathlib import Path

from tests.helpers import (
    AUDIT_REPORT_PY,
    CLI_PY,
    CONTROL_PLANE_PY,
    CODE_REVIEW_ADAPTER_PY,
    FINAL_GATE_PY,
    INGEST_FINDINGS_PY,
    LIST_THREADS_PY,
    POST_REPLY_PY,
    PUBLISH_FINDING_PY,
    PREPARE_CODE_REVIEW_PY,
    REVIEW_TO_FINDINGS_PY,
    RESOLVE_THREAD_PY,
    RUN_LOCAL_REVIEW_PY,
    RUN_ONCE_PY,
    SCRIPT,
    PythonScriptTestCase,
)


class PythonWrapperCLITest(PythonScriptTestCase):
    def test_cli_help_lists_unified_commands(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--machine", result.stdout)
        self.assertIn("--human", result.stdout)
        self.assertIn("review", result.stdout)
        self.assertIn("threads", result.stdout)
        self.assertIn("findings", result.stdout)
        self.assertIn("adapter", result.stdout)
        self.assertIn("review-to-findings", result.stdout)
        self.assertNotIn("cr-loop", result.stdout)
        self.assertNotIn("control-plane", result.stdout)
        self.assertNotIn("run-once", result.stdout)
        self.assertNotIn("session-engine", result.stdout)

    def test_cli_review_help_uses_high_level_alias_text(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "review", "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: cli.py review", result.stdout)
        self.assertIn("High-level PR review entrypoint.", result.stdout)
        self.assertIn("waits for external review findings", result.stdout)
        self.assertIn("re-run the same review command", result.stdout)
        self.assertIn("Default output is a structured JSON summary.", result.stdout)
        self.assertIn("--human", result.stdout)
        self.assertIn("--machine", result.stdout)
        self.assertNotIn("cr-loop", result.stdout)
        self.assertNotIn("{ingest,local,mixed,remote}", result.stdout)

    def test_cli_adapter_help_matches_orchestration_behavior(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "adapter", "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: cli.py [--human|--machine] adapter", result.stdout)
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
                "review",
                self.repo,
                self.pr,
                "--input",
                "-",
            ],
            stdin="[]",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(
            set(summary),
            {"artifact_path", "counts", "exit_code", "item_id", "item_kind", "next_action", "pr_number", "reason_code", "repo", "status", "waiting_on"},
        )
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["counts"]["blocking_items_count"], 0)
        self.assertIn("pr-77", summary["artifact_path"])
        self.assertEqual(summary["next_action"], "No action required.")
        self.assertEqual(summary["reason_code"], "PASSED")
        self.assertIsNone(summary["waiting_on"])

    def test_cli_review_human_flag_keeps_human_text(self):
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
                "review",
                self.repo,
                self.pr,
                "--input",
                "-",
                "--human",
            ],
            stdin="[]",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cr-loop PASSED", result.stdout)
        self.assertNotIn("\"status\"", result.stdout)

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
                "review",
                self.repo,
                self.pr,
                "--input",
                "-",
                "--machine",
            ],
            stdin="[]",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["reason_code"], "PASSED")
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

    def test_cli_findings_help_mentions_source_required_for_sync(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "findings", "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: cli.py findings", result.stdout)
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
        resolved = self.run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "resolve-local-item",
                self.repo,
                self.pr,
                item_id,
                "fix",
                "--note",
                "Fixed locally before rerunning review.",
            ]
        )
        self.assertEqual(resolved.returncode, 0, resolved.stderr)

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
            {"artifact_path", "counts", "exit_code", "item_id", "item_kind", "next_action", "pr_number", "reason_code", "repo", "status", "waiting_on"},
        )
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["repo"], self.repo)
        self.assertEqual(summary["pr_number"], self.pr)
        self.assertEqual(summary["exit_code"], 5)
        self.assertGreaterEqual(summary["counts"]["blocking_items_count"], 1)
        self.assertEqual(summary["item_kind"], "local_finding")
        self.assertTrue(summary["item_id"].startswith("local-finding:"))
        self.assertIn("loop-request-", summary["artifact_path"])
        self.assertIn("Address the finding", summary["next_action"])
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
        self.assertIn("Address the finding", summary["next_action"])
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
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(json.loads(seen_args.read_text(encoding="utf-8")), ["--human", "--machine"])

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
        self.assertEqual(summary["reason_code"], "MISSING_GH_CLI")
        self.assertEqual(summary["waiting_on"], "github_cli")
        self.assertIn("gh", result.stderr)

    def test_run_local_review_requires_explicit_source_for_sync(self):
        adapter = Path(self.temp_dir.name) / "adapter.py"
        adapter.write_text("import json\nprint(json.dumps([]))\n", encoding="utf-8")

        result = self.run_cmd(
            [
                sys.executable,
                str(RUN_LOCAL_REVIEW_PY),
                "--sync",
                self.repo,
                self.pr,
                sys.executable,
                str(adapter),
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an explicit --source", result.stderr)

    def test_ingest_findings_requires_explicit_source_for_sync(self):
        payload_file = Path(self.temp_dir.name) / "findings.json"
        payload_file.write_text(
            json.dumps(
                [
                    {
                        "title": "Needs source",
                        "body": "Sync should not default to a shared namespace.",
                        "path": "src/source.py",
                        "line": 4,
                    }
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(INGEST_FINDINGS_PY),
                "--sync",
                "--input",
                str(payload_file),
                self.repo,
                self.pr,
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an explicit --source", result.stderr)

    def test_cli_dispatches_run_once(self):
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

        result = self.run_cmd([sys.executable, str(CLI_PY), "run-once", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("github-thread:THREAD_CLI", result.stdout)

    def test_cli_dispatches_session_engine_list_items(self):
        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        payload = json.dumps(
            [
                {
                    "title": "CLI list-items",
                    "body": "Ensure unified CLI dispatches to session engine correctly.",
                    "path": "README.md",
                    "line": 12,
                    "severity": "P3",
                    "category": "docs",
                }
            ]
        )
        self.run_cmd(
            [sys.executable, str(SCRIPT), "ingest-local", self.repo, self.pr, "--source", "local-agent:test"],
            stdin=payload,
            check=True,
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "session-engine",
                "list-items",
                self.repo,
                self.pr,
                "--item-kind",
                "local_finding",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("local-finding:", result.stdout)
        self.assertIn("CLI list-items", result.stdout)

    def test_run_local_review_python_ingests_findings(self):
        adapter = Path(self.temp_dir.name) / "adapter.py"
        adapter.write_text(
            "import json\nprint(json.dumps([{'title':'py-adapter','body':'body','path':'src/a.py','line':4}]))\n",
            encoding="utf-8",
        )

        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        result = self.run_cmd(
            [
                sys.executable,
                str(RUN_LOCAL_REVIEW_PY),
                "--source",
                "local-agent:test",
                self.repo,
                self.pr,
                sys.executable,
                str(adapter),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Created 1 local item", result.stdout)

    def test_ingest_findings_python_accepts_envelope_payload(self):
        payload_file = Path(self.temp_dir.name) / "findings.json"
        payload_file.write_text(
            json.dumps(
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
                }
            ),
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(INGEST_FINDINGS_PY),
                "--source",
                "local-agent:external-review",
                "--input",
                str(payload_file),
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Created 1 local item", result.stdout)

        list_result = self.run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "list-items",
                self.repo,
                self.pr,
                "--item-kind",
                "local_finding",
            ],
            check=True,
        )
        item = json.loads(list_result.stdout.strip())
        self.assertEqual(item["path"], "src/envelope.py")
        self.assertEqual(item["line"], 9)
        self.assertEqual(item["body"], "Imported from another review tool.")

    def test_cli_dispatches_ingest_findings(self):
        payload_file = Path(self.temp_dir.name) / "findings-ndjson.jsonl"
        payload_file.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "check": "null-guard",
                            "description": "Potential null dereference.",
                            "filename": "src/cli_ingest.py",
                            "line": 5,
                            "severity": "P1",
                        }
                    )
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "ingest-findings",
                "--source",
                "local-agent:cli-import",
                "--input",
                str(payload_file),
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Created 1 local item", result.stdout)

    def test_control_plane_remote_runs_run_once(self):
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

        result = self.run_cmd([sys.executable, str(CONTROL_PLANE_PY), "remote", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("github-thread:THREAD_REMOTE", result.stdout)

    def test_control_plane_remote_gate_reuses_run_once_snapshot(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str((Path(self.temp_dir.name) / "gh_gate_state.json").as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"graphql_calls": 0}}))

args = sys.argv[1:]
if args[:2] == ['api', 'graphql']:
    payload = json.loads(state_file.read_text())
    payload['graphql_calls'] += 1
    state_file.write_text(json.dumps(payload))
    print(json.dumps({{
        'data': {{
            'repository': {{
                'pullRequest': {{
                    'reviewThreads': {{
                        'pageInfo': {{'hasNextPage': False, 'endCursor': None}},
                        'nodes': [{{
                            'id': 'THREAD_GATE',
                            'isResolved': True,
                            'isOutdated': False,
                            'path': 'src/gate.py',
                            'line': 4,
                            'firstComment': {{'nodes': [{{'url': 'https://example.test/thread/gate', 'body': 'gate'}}]}},
                            'latestComment': {{'nodes': [{{'url': 'https://example.test/thread/gate', 'body': 'gate'}}]}},
                        }}]
                    }}
                }}
            }}
        }}
    }}))
elif args[:2] == ['api', 'user']:
    print(json.dumps({{'login': 'agent-login'}}))
elif args[:2] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd([sys.executable, str(CONTROL_PLANE_PY), "remote", "--gate", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads((Path(self.temp_dir.name) / "gh_gate_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["graphql_calls"], 1)

    def test_control_plane_mixed_json_runs_sync_and_ingest(self):
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
                            'id': 'THREAD_MIXED',
                            'isResolved': False,
                            'isOutdated': False,
                            'path': 'src/mixed.py',
                            'line': 8,
                            'firstComment': {'nodes': [{'url': 'https://example.test/thread/mixed', 'body': 'mixed'}]},
                            'latestComment': {'nodes': [{'url': 'https://example.test/thread/mixed', 'body': 'mixed'}]},
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

        payload_file = Path(self.temp_dir.name) / "mixed-findings.json"
        payload_file.write_text(
            json.dumps(
                [
                    {
                        "title": "Mixed finding",
                        "body": "Imported into mixed flow.",
                        "path": "src/mixed_local.py",
                        "line": 11,
                    }
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CONTROL_PLANE_PY),
                "mixed",
                "json",
                "--input",
                str(payload_file),
                self.repo,
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("github-thread:THREAD_MIXED", result.stdout)
        self.assertIn("Created 1 local item", result.stdout)

    def test_control_plane_stops_after_run_once_failure(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import sys
sys.stderr.write('graphql failed\\n')
raise SystemExit(1)
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        payload_file = Path(self.temp_dir.name) / "mixed-findings.json"
        payload_file.write_text(
            json.dumps(
                [
                    {
                        "title": "Should not ingest after remote failure",
                        "body": "Control plane must stop on the first failed stage.",
                        "path": "src/ignored.py",
                        "line": 11,
                    }
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CONTROL_PLANE_PY),
                "mixed",
                "json",
                "--input",
                str(payload_file),
                self.repo,
                self.pr,
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Created 1 local item", result.stdout)

        session_file = self.session_file()
        self.assertFalse(session_file.exists())

    def test_control_plane_mixed_code_review_accepts_dash_input_from_stdin(self):
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
else:
    raise SystemExit(f'unhandled gh args: {sys.argv[1:]}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        payload = json.dumps(
            [
                {
                    "title": "stdin bridge finding",
                    "body": "Imported through --input -.",
                    "path": "src/stdin_bridge.py",
                    "line": 14,
                    "severity": "P2",
                }
            ]
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CONTROL_PLANE_PY),
                "mixed",
                "code-review",
                "--input",
                "-",
                self.repo,
                self.pr,
            ],
            stdin=payload,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Created 1 local item", result.stdout)

        list_result = self.run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "list-items",
                self.repo,
                self.pr,
                "--item-kind",
                "local_finding",
            ],
            check=True,
        )
        item = json.loads(list_result.stdout.strip())
        self.assertEqual(item["title"], "stdin bridge finding")
        self.assertEqual(item["line"], 14)

    def test_control_plane_local_adapter_runs_adapter(self):
        adapter = Path(self.temp_dir.name) / "adapter.py"
        adapter.write_text(
            "import json\nprint(json.dumps([{'title':'adapter finding','body':'body','path':'src/a.py','line':4}]))\n",
            encoding="utf-8",
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(CONTROL_PLANE_PY),
                "local",
                "adapter",
                self.repo,
                self.pr,
                sys.executable,
                str(adapter),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Created 1 local item", result.stdout)

    def test_control_plane_rejects_remote_with_producer(self):
        result = self.run_cmd(
            [sys.executable, str(CONTROL_PLANE_PY), "remote", "code-review", self.repo, self.pr]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("remote expects", result.stderr)

    def test_control_plane_requires_json_input_for_code_review(self):
        result = self.run_cmd(
            [sys.executable, str(CONTROL_PLANE_PY), "local", "code-review", self.repo, self.pr]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires findings JSON", result.stderr)

    def test_control_plane_rejects_ingest_code_review(self):
        result = self.run_cmd(
            [sys.executable, str(CONTROL_PLANE_PY), "ingest", "code-review", self.repo, self.pr]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ingest mode only supports producer=json", result.stderr)

    def test_control_plane_requires_explicit_source_for_sync(self):
        result = self.run_cmd(
            [sys.executable, str(CONTROL_PLANE_PY), "local", "json", "--sync", self.repo, self.pr]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an explicit --source", result.stderr)

    def test_prepare_code_review_emits_bridge_prompt(self):
        result = self.run_cmd(
            [sys.executable, str(PREPARE_CODE_REVIEW_PY), "mixed", self.repo, self.pr]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["producer"], "code-review")
        self.assertEqual(payload["mode"], "mixed")
        self.assertIn("emit findings json", " ".join(payload["instructions"]).lower())
        self.assertIn("code-review-adapter", payload["adapter_backend"])
        self.assertIn("review-to-findings", payload["review_to_findings_command"])
        self.assertIn("control-plane mixed code-review", payload["ingest_command"])
        self.assertIn("python3 scripts/cli.py", payload["adapter_backend"])
        self.assertIn("python3 scripts/cli.py", payload["review_to_findings_command"])
        self.assertIn("python3 scripts/cli.py", payload["ingest_command"])
        self.assertNotIn("gh-address-cr/scripts/cli.py", payload["adapter_backend"])
        self.assertNotIn("gh-address-cr/scripts/cli.py", payload["review_to_findings_command"])
        self.assertNotIn("gh-address-cr/scripts/cli.py", payload["ingest_command"])
        self.assertIn("/octo__example/pr-77", payload["workspace_dir"])
        self.assertTrue(payload["findings_output_path"].endswith("/octo__example/pr-77/code-review-findings.json"))
        self.assertTrue(payload["reply_output_path"].endswith("/octo__example/pr-77/reply.md"))
        self.assertTrue(payload["loop_request_path"].endswith("/octo__example/pr-77/loop-request.json"))
        self.assertTrue(payload["review_to_findings_command"].endswith("/octo__example/pr-77"))

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

    def test_code_review_adapter_normalizes_findings(self):
        payload = json.dumps(
            {
                "findings": [
                    {
                        "check": "null-guard",
                        "description": "Potential null dereference.",
                        "filename": "src/code_review.py",
                        "position": 9,
                        "severity": "P1",
                    }
                ]
            }
        )
        result = self.run_cmd(
            [sys.executable, str(CODE_REVIEW_ADAPTER_PY)],
            stdin=payload,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        findings = json.loads(result.stdout)
        self.assertEqual(findings[0]["title"], "null-guard")
        self.assertEqual(findings[0]["path"], "src/code_review.py")
        self.assertEqual(findings[0]["line"], 9)

    def test_cli_dispatches_prepare_code_review(self):
        result = self.run_cmd(
            [sys.executable, str(CLI_PY), "prepare-code-review", "local", self.repo, self.pr]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode"], "local")

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

    def test_ingest_findings_python_accepts_stdin_array(self):
        payload = json.dumps(
            [
                {
                    "title": "stdin finding",
                    "body": "Imported through stdin.",
                    "path": "src/stdin.py",
                    "line": 3,
                    "severity": "P3",
                    "category": "docs",
                }
            ]
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(INGEST_FINDINGS_PY),
                "--source",
                "local-agent:stdin-review",
                self.repo,
                self.pr,
            ],
            stdin=payload,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Created 1 local item", result.stdout)

        list_result = self.run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "list-items",
                self.repo,
                self.pr,
                "--item-kind",
                "local_finding",
            ],
            check=True,
        )
        item = json.loads(list_result.stdout.strip())
        self.assertEqual(item["path"], "src/stdin.py")
        self.assertEqual(item["line"], 3)
        self.assertEqual(item["source"], "local-agent:stdin-review")

    def test_publish_finding_python_dry_run_uses_diff_position(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:3] == ['pr', 'view', '77']:
    print('deadbeefdeadbeefdeadbeefdeadbeefdeadbeef')
elif args[:2] == ['api', 'repos/octo/example/pulls/77/files']:
    page = next((arg.split('=')[1] for arg in args if arg.startswith('page=')), '1')
    if page == '1':
        print(json.dumps([{'filename':'src/a.py','patch':'@@ -1,1 +1,4 @@\\n line1\\n+line2\\n+line3\\n+line4'}]))
    else:
        print('[]')
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        payload = json.dumps(
            [
                {
                    "title": "Publish me",
                    "body": "Dry-run publication.",
                    "path": "src/a.py",
                    "line": 4,
                    "severity": "P3",
                    "category": "docs",
                }
            ]
        )
        ingest = self.run_cmd(
            [sys.executable, str(SCRIPT), "ingest-local", self.repo, self.pr, "--source", "local-agent:test"],
            stdin=payload,
            check=True,
        )
        self.assertIn("Created 1 local item", ingest.stdout)

        list_result = self.run_cmd([sys.executable, str(SCRIPT), "list-items", self.repo, self.pr, "--item-kind", "local_finding"], check=True)
        item_id = json.loads(list_result.stdout.strip())["item_id"]
        result = self.run_cmd(
            [
                sys.executable,
                str(PUBLISH_FINDING_PY),
                "--dry-run",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                item_id,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("position=4", result.stdout)

    def test_publish_finding_python_dry_run_handles_multiple_pages(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:3] == ['pr', 'view', '77']:
    print('deadbeefdeadbeefdeadbeefdeadbeefdeadbeef')
elif args[:2] == ['api', 'repos/octo/example/pulls/77/files']:
    page = next((arg.split('=')[1] for arg in args if arg.startswith('page=')), '1')
    if page == '1':
        print(json.dumps([{'filename':'src/other.py','patch':'@@ -1,1 +1,1 @@\\n line1\\n+line2'}]))
    elif page == '2':
        print(json.dumps([{'filename':'src/a.py','patch':'@@ -1,1 +1,4 @@\\n line1\\n+line2\\n+line3\\n+line4'}]))
    else:
        print('[]')
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        payload = json.dumps(
            [
                {
                    "title": "Publish me",
                    "body": "Dry-run publication.",
                    "path": "src/a.py",
                    "line": 4,
                    "severity": "P3",
                    "category": "docs",
                }
            ]
        )
        self.run_cmd(
            [sys.executable, str(SCRIPT), "ingest-local", self.repo, self.pr, "--source", "local-agent:test"],
            stdin=payload,
            check=True,
        )
        list_result = self.run_cmd([sys.executable, str(SCRIPT), "list-items", self.repo, self.pr, "--item-kind", "local_finding"], check=True)
        item_id = json.loads(list_result.stdout.strip())["item_id"]

        result = self.run_cmd(
            [
                sys.executable,
                str(PUBLISH_FINDING_PY),
                "--dry-run",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                item_id,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("position=4", result.stdout)

    def test_publish_finding_python_reports_structured_success(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:3] == ['pr', 'view', '77']:
    print('deadbeefdeadbeefdeadbeefdeadbeefdeadbeef')
elif args[:2] == ['api', 'repos/octo/example/pulls/77/files']:
    page = next((arg.split('=')[1] for arg in args if arg.startswith('page=')), '1')
    if page == '1':
        print(json.dumps([{'filename':'src/a.py','patch':'@@ -1,1 +1,4 @@\\n line1\\n+line2\\n+line3\\n+line4'}]))
    else:
        print('[]')
elif args[:2] == ['api', 'repos/octo/example/pulls/77/comments']:
    print(json.dumps({'id': 321, 'html_url': 'https://example.test/comment/321'}))
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        payload = json.dumps(
            [
                {
                    "title": "Publish me",
                    "body": "Non-dry-run publication.",
                    "path": "src/a.py",
                    "line": 4,
                    "severity": "P3",
                    "category": "docs",
                }
            ]
        )
        self.run_cmd(
            [sys.executable, str(SCRIPT), "ingest-local", self.repo, self.pr, "--source", "local-agent:test"],
            stdin=payload,
            check=True,
        )
        list_result = self.run_cmd([sys.executable, str(SCRIPT), "list-items", self.repo, self.pr, "--item-kind", "local_finding"], check=True)
        item_id = json.loads(list_result.stdout.strip())["item_id"]

        result = self.run_cmd(
            [
                sys.executable,
                str(PUBLISH_FINDING_PY),
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                item_id,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "succeeded")
        self.assertEqual(summary["remote_status"], "succeeded")
        self.assertEqual(summary["session_status"], "succeeded")
        self.assertEqual(summary["comment_id"], 321)
        self.assertEqual(summary["comment_url"], "https://example.test/comment/321")

        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        item = session["items"][item_id]
        self.assertTrue(item["published"])
        self.assertEqual(item["published_ref"], "321")

    def test_publish_finding_python_reuses_pr_files_cache_for_same_head(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "publish_cache_state.json"
        state_file.write_text(json.dumps({"files_calls": 0, "head_calls": 0}), encoding="utf-8")
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file)!r})
state = json.loads(state_file.read_text(encoding='utf-8'))
args = sys.argv[1:]
if args[:3] == ['pr', 'view', '77']:
    state['head_calls'] += 1
    state_file.write_text(json.dumps(state), encoding='utf-8')
    print('deadbeefdeadbeefdeadbeefdeadbeefdeadbeef')
elif args[:2] == ['api', 'repos/octo/example/pulls/77/files']:
    state['files_calls'] += 1
    state_file.write_text(json.dumps(state), encoding='utf-8')
    page = next((arg.split('=')[1] for arg in args if arg.startswith('page=')), '1')
    if page == '1':
        print(json.dumps([{{'filename':'src/a.py','patch':'@@ -1,1 +1,4 @@\\n line1\\n+line2\\n+line3\\n+line4'}}]))
    else:
        print('[]')
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        payload = json.dumps(
            [
                {
                    "title": "Publish me",
                    "body": "Dry-run publication.",
                    "path": "src/a.py",
                    "line": 4,
                    "severity": "P3",
                    "category": "docs",
                }
            ]
        )
        self.run_cmd(
            [sys.executable, str(SCRIPT), "ingest-local", self.repo, self.pr, "--source", "local-agent:test"],
            stdin=payload,
            check=True,
        )

        list_result = self.run_cmd([sys.executable, str(SCRIPT), "list-items", self.repo, self.pr, "--item-kind", "local_finding"], check=True)
        item_id = json.loads(list_result.stdout.strip())["item_id"]

        for _ in range(2):
            result = self.run_cmd(
                [
                    sys.executable,
                    str(PUBLISH_FINDING_PY),
                    "--dry-run",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                    item_id,
                ]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("position=4", result.stdout)

        state = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(state["head_calls"], 2)
        self.assertEqual(state["files_calls"], 2)

    def test_run_once_python_syncs_session_with_mocked_gh(self):
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

        result = self.run_cmd([sys.executable, str(RUN_ONCE_PY), "--audit-id", "test", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("== PR Review Threads ==", result.stdout)
        self.assertIn("github-thread:THREAD_A", result.stdout)

    def test_run_once_python_lists_reopened_thread_as_unhandled(self):
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

        first = self.run_cmd([sys.executable, str(RUN_ONCE_PY), self.repo, self.pr])
        self.assertEqual(first.returncode, 0, first.stderr)

        phase_file.write_text("reopened", encoding="utf-8")
        second = self.run_cmd([sys.executable, str(RUN_ONCE_PY), self.repo, self.pr])
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("github-thread:THREAD_REOPENED", second.stdout)

    def test_run_once_python_lists_stale_thread_as_unhandled(self):
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

        result = self.run_cmd([sys.executable, str(RUN_ONCE_PY), self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"item_id": "github-thread:THREAD_STALE"', result.stdout)
        self.assertIn('"status": "STALE"', result.stdout)

    def test_final_gate_python_passes_on_resolved_threads(self):
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

        result = self.run_cmd([sys.executable, str(FINAL_GATE_PY), "--no-auto-clean", "--audit-id", "gate-test", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("== Current Run Snapshot ==", result.stdout)
        self.assertNotIn("GitHub threads: total 1;", result.stdout)
        self.assertNotIn("Local findings: total 0;", result.stdout)
        self.assertIn("== Gate Result ==", result.stdout)
        self.assertIn("Verified: 0 Unresolved Threads found", result.stdout)
        self.assertIn("Verified: 0 Pending Reviews found", result.stdout)
        self.assertIn("Session blocking items: 0", result.stdout)
        self.assertIn("== Machine Gate Diagnostics ==", result.stdout)
        self.assertIn("github_threads_total_count=1", result.stdout)
        self.assertIn("github_threads_new_count=1", result.stdout)
        self.assertIn("github_threads_handled_this_run_count=1", result.stdout)
        self.assertIn("github_threads_unresolved_count=0", result.stdout)
        self.assertIn("local_findings_total_count=0", result.stdout)
        self.assertIn("local_findings_new_count=0", result.stdout)
        self.assertIn("local_findings_handled_this_run_count=0", result.stdout)
        self.assertIn("local_findings_unresolved_count=0", result.stdout)
        self.assertIn("Audit summary file:", result.stdout)

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
                            'firstComment': {{'nodes': [{{'url': 'https://example.test/thread/done', 'body': 'Done'}}]}},
                            'latestComment': {{'nodes': [{{'url': 'https://example.test/thread/done', 'body': 'Done'}}]}},
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

        result = self.run_cmd([sys.executable, str(FINAL_GATE_PY), "--no-auto-clean", self.repo, self.pr])
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("Pending review count: 1", result.stdout)
        self.assertIn("pending review(s)", result.stderr)

    def test_list_threads_python_outputs_normalized_rows(self):
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
                            'id': 'THREAD_LIST',
                            'isResolved': False,
                            'isOutdated': True,
                            'path': 'src/list.py',
                            'line': 2,
                            'firstComment': {'nodes': [{'url': 'https://example.test/thread/list-first', 'body': 'first'}]},
                            'latestComment': {'nodes': [{'url': 'https://example.test/thread/list-latest', 'body': 'latest'}]},
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

        result = self.run_cmd([sys.executable, str(LIST_THREADS_PY), self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout.strip())
        self.assertEqual(row["id"], "THREAD_LIST")
        self.assertEqual(row["url"], "https://example.test/thread/list-latest")
        self.assertEqual(row["comment_source"], "latest")

    def test_post_reply_python_dry_run_prints_body(self):
        reply_file = Path(self.temp_dir.name) / "reply.md"
        reply_file.write_text("Reply body", encoding="utf-8")

        result = self.run_cmd(
            [
                sys.executable,
                str(POST_REPLY_PY),
                "--dry-run",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "THREAD_REPLY",
                str(reply_file),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[dry-run] Would reply to thread: THREAD_REPLY", result.stdout)
        self.assertIn("Reply body", result.stdout)

    def test_post_reply_submits_pending_review_for_current_user(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str((Path(self.temp_dir.name) / "gh_state.json").as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"submitted": [], "review_calls": 0}}))

args = sys.argv[1:]
if args[:2] == ['api', 'graphql']:
    query = next((arg.split('=', 1)[1] for arg in args if arg.startswith('query=')), '')
    if 'submitPullRequestReview' in query:
        payload = json.loads(state_file.read_text())
        payload['submitted'].append('REV_NODE_101')
        state_file.write_text(json.dumps(payload))
        print(json.dumps({{'data': {{'submit0': {{'pullRequestReview': {{'id': 'REV_NODE_101'}}}}}}}}))
    else:
        print(json.dumps({{'data': {{'addPullRequestReviewThreadReply': {{'comment': {{'url': 'https://example.test/reply'}}}}}}}}))
elif args[:2] == ['api', 'user']:
    print(json.dumps({{'login': 'octocat'}}))
elif len(args) >= 2 and args[0] == 'api' and args[1].startswith('repos/octo/example/pulls/77/reviews'):
    payload = json.loads(state_file.read_text())
    payload['review_calls'] += 1
    state_file.write_text(json.dumps(payload))
    if 'page=2' in args[1]:
        print(json.dumps([]))
    else:
        print(json.dumps([
            {{'node_id': 'REV_NODE_101', 'id': 101, 'state': 'PENDING', 'user': {{'login': 'octocat'}}}},
            {{'node_id': 'REV_NODE_202', 'id': 202, 'state': 'COMMENTED', 'user': {{'login': 'octocat'}}}},
            {{'node_id': 'REV_NODE_303', 'id': 303, 'state': 'PENDING', 'user': {{'login': 'someone-else'}}}}
        ]))
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        reply_file = Path(self.temp_dir.name) / "reply.md"
        reply_file.write_text("Reply body", encoding="utf-8")
        result = self.run_cmd(
            [
                sys.executable,
                str(POST_REPLY_PY),
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "THREAD_REPLY",
                str(reply_file),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["reply_status"], "succeeded")
        self.assertEqual(payload["review_submit_status"], "succeeded")
        self.assertEqual(payload["reply_url"], "https://example.test/reply")
        state = json.loads((Path(self.temp_dir.name) / "gh_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["submitted"], ["REV_NODE_101"])
        self.assertEqual(state["review_calls"], 2)

    def test_post_reply_submits_preexisting_pending_review(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str((Path(self.temp_dir.name) / "gh_state_existing.json").as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"submitted": [], "review_calls": 0}}))

args = sys.argv[1:]
if args[:2] == ['api', 'graphql']:
    query = next((arg.split('=', 1)[1] for arg in args if arg.startswith('query=')), '')
    if 'submitPullRequestReview' in query:
        payload = json.loads(state_file.read_text())
        payload['submitted'].append('777')
        state_file.write_text(json.dumps(payload))
        print(json.dumps({{'data': {{'submit0': {{'pullRequestReview': {{'id': '777'}}}}}}}}))
    else:
        print(json.dumps({{'data': {{'addPullRequestReviewThreadReply': {{'comment': {{'url': 'https://example.test/reply-existing'}}}}}}}}))
elif args[:2] == ['api', 'user']:
    print(json.dumps({{'login': 'octocat'}}))
elif len(args) >= 2 and args[0] == 'api' and args[1].startswith('repos/octo/example/pulls/77/reviews'):
    payload = json.loads(state_file.read_text())
    payload['review_calls'] += 1
    state_file.write_text(json.dumps(payload))
    if 'page=2' in args[1]:
        print(json.dumps([]))
    else:
        print(json.dumps([
            {{'node_id': 'REV_NODE_777', 'id': 777, 'state': 'PENDING', 'user': {{'login': 'octocat'}}}},
            {{'node_id': 'REV_NODE_202', 'id': 202, 'state': 'COMMENTED', 'user': {{'login': 'octocat'}}}}
        ]))
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        reply_file = Path(self.temp_dir.name) / "reply-existing.md"
        reply_file.write_text("Reply body", encoding="utf-8")
        result = self.run_cmd(
            [
                sys.executable,
                str(POST_REPLY_PY),
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "THREAD_REPLY",
                str(reply_file),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["reply_status"], "succeeded")
        self.assertEqual(payload["review_submit_status"], "succeeded")
        self.assertEqual(payload["reply_url"], "https://example.test/reply-existing")
        state = json.loads((Path(self.temp_dir.name) / "gh_state_existing.json").read_text(encoding="utf-8"))
        self.assertEqual(state["submitted"], ["777"])
        self.assertEqual(state["review_calls"], 2)

    def test_post_reply_reports_unknown_when_submit_fails_after_reply(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str((Path(self.temp_dir.name) / "gh_state_submit_fail.json").as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"submitted": [], "review_calls": 0}}))

args = sys.argv[1:]
if args[:2] == ['api', 'graphql']:
    query = next((arg.split('=', 1)[1] for arg in args if arg.startswith('query=')), '')
    if 'submitPullRequestReview' in query:
        sys.stderr.write('submit failed\\n')
        raise SystemExit(1)
    print(json.dumps({{'data': {{'addPullRequestReviewThreadReply': {{'comment': {{'url': 'https://example.test/reply-partial'}}}}}}}}))
elif args[:2] == ['api', 'user']:
    print(json.dumps({{'login': 'octocat'}}))
elif len(args) >= 2 and args[0] == 'api' and args[1].startswith('repos/octo/example/pulls/77/reviews'):
    payload = json.loads(state_file.read_text())
    payload['review_calls'] += 1
    state_file.write_text(json.dumps(payload))
    if 'page=2' in args[1]:
        print(json.dumps([]))
    else:
        print(json.dumps([
            {{'node_id': 'REV_NODE_888', 'id': 888, 'state': 'PENDING', 'user': {{'login': 'octocat'}}}}
        ]))
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        reply_file = Path(self.temp_dir.name) / "reply-partial.md"
        reply_file.write_text("Reply body", encoding="utf-8")
        result = self.run_cmd(
            [
                sys.executable,
                str(POST_REPLY_PY),
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "THREAD_REPLY",
                str(reply_file),
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "unknown")
        self.assertEqual(payload["reply_status"], "succeeded")
        self.assertEqual(payload["review_submit_status"], "unknown")
        self.assertEqual(payload["reply_url"], "https://example.test/reply-partial")
        self.assertIn("submit failed", payload["error"])

    def test_cli_machine_rejects_unsupported_subcommand_before_running_it(self):
        result = self.run_cmd([sys.executable, str(CLI_PY), "--machine", "final-gate", self.repo, self.pr])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--machine and --human are only supported for review, threads, findings, and adapter.", result.stderr)
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

        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        payload = json.dumps(
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
        self.run_cmd(
            [sys.executable, str(SCRIPT), "ingest-local", self.repo, self.pr, "--source", "local-agent:test"],
            stdin=payload,
            check=True,
        )

        result = self.run_cmd([sys.executable, str(FINAL_GATE_PY), "--no-auto-clean", self.repo, self.pr])
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

        result = self.run_cmd([sys.executable, str(FINAL_GATE_PY), "--auto-clean", self.repo, self.pr])
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

        result = self.run_cmd([sys.executable, str(FINAL_GATE_PY), "--auto-clean", "--audit-id", "archive-run", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.workspace_dir().exists())
        self.assertTrue(self.archive_root().exists())

        archived_runs = sorted(self.archive_root().iterdir())
        self.assertEqual(len(archived_runs), 1)
        archived_workspace = archived_runs[0]
        self.assertTrue((archived_workspace / "audit.jsonl").exists())
        self.assertTrue((archived_workspace / "trace.jsonl").exists())
        self.assertTrue((archived_workspace / "audit_summary.md").exists())
        self.assertTrue((archived_workspace / "session.json").exists())

        trace_lines = (archived_workspace / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(trace_lines)
        self.assertTrue(any(json.loads(line).get("run_id") == "archive-run" for line in trace_lines if line.strip()))

    def test_audit_report_filters_trace_to_one_run_id(self):
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

        first = self.run_cmd([sys.executable, str(FINAL_GATE_PY), "--no-auto-clean", "--audit-id", "run-a", self.repo, self.pr])
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_cmd([sys.executable, str(FINAL_GATE_PY), "--no-auto-clean", "--audit-id", "run-b", self.repo, self.pr])
        self.assertEqual(second.returncode, 0, second.stderr)

        report = self.run_cmd([sys.executable, str(AUDIT_REPORT_PY), "--run-id", "run-a", self.repo, self.pr])
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertIn("Run: run-a", report.stdout)
        self.assertIn('"run_id": "run-a"', report.stdout)
        self.assertIn('"action": "sync-github"', report.stdout)
        self.assertIn('"action": "gate"', report.stdout)
        self.assertNotIn('"run_id": "run-b"', report.stdout)

    def test_resolve_thread_python_updates_session(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'resolveReviewThread': {
                'thread': {
                    'id': 'THREAD_RESOLVE',
                    'isResolved': True,
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

        payload = json.dumps(
            [
                {
                    "id": "THREAD_RESOLVE",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/resolve.py",
                    "line": 9,
                    "body": "Resolve me.",
                    "url": "https://example.test/thread/resolve",
                }
            ]
        )
        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        self.run_cmd(
            [sys.executable, str(SCRIPT), "sync-github", self.repo, self.pr],
            stdin=payload,
            check=True,
        )

        result = self.run_cmd(
            [
                sys.executable,
                str(RESOLVE_THREAD_PY),
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "THREAD_RESOLVE",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["remote_status"], "succeeded")
        self.assertEqual(payload["session_status"], "succeeded")
        self.assertTrue(payload["resolved"])
        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        item = session["items"]["github-thread:THREAD_RESOLVE"]
        self.assertEqual(item["status"], "CLOSED")
        self.assertTrue(item["handled"])

    def test_resolve_thread_python_succeeds_when_item_not_yet_synced(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] == ['api', 'graphql']:
    print(json.dumps({
        'data': {
            'resolveReviewThread': {
                'thread': {
                    'id': 'THREAD_ONLY_REMOTE',
                    'isResolved': True,
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

        result = self.run_cmd(
            [
                sys.executable,
                str(RESOLVE_THREAD_PY),
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "THREAD_ONLY_REMOTE",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["session_status"], "missing")
        handled_file = self.github_dir() / "handled_threads.txt"
        self.assertIn("THREAD_ONLY_REMOTE", handled_file.read_text(encoding="utf-8"))

    def test_resolve_thread_python_requires_explicit_repo_and_pr(self):
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

        result = self.run_cmd([sys.executable, str(RESOLVE_THREAD_PY), "THREAD_NEEDS_CONTEXT"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--repo and --pr are required", result.stderr)

    def test_mark_handled_appends_without_clobbering_existing_entries(self):
        handled_file = self.github_dir() / "handled_threads.txt"
        handled_file.parent.mkdir(parents=True, exist_ok=True)
        handled_file.write_text("THREAD_EXISTING\n", encoding="utf-8")
        payload = json.dumps(
            [
                {
                    "id": "THREAD_NEW",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/thread.py",
                    "line": 8,
                    "body": "Mark handled test.",
                    "url": "https://example.test/thread/new",
                }
            ]
        )
        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        self.run_cmd([sys.executable, str(SCRIPT), "sync-github", self.repo, self.pr], stdin=payload, check=True)

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "mark-handled",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "THREAD_NEW",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(handled_file.read_text(encoding="utf-8").splitlines(), ["THREAD_EXISTING", "THREAD_NEW"])

    def test_mark_handled_routes_local_finding_prefix_to_resolve_local_item(self):
        self.run_cmd([sys.executable, str(SCRIPT), "init", self.repo, self.pr], check=True)
        self.run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "ingest-local",
                self.repo,
                self.pr,
                "--source",
                "local-agent:test",
            ],
            stdin=json.dumps(
                [
                    {
                        "title": "Local finding",
                        "body": "Resolve this locally.",
                        "path": "src/local.py",
                        "line": 11,
                    }
                ]
            ),
            check=True,
        )
        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        local_id = next(item_id for item_id, item in session["items"].items() if item["item_kind"] == "local_finding")

        result = self.run_cmd(
            [
                sys.executable,
                str(CLI_PY),
                "mark-handled",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                local_id,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        session = json.loads(self.session_file().read_text(encoding="utf-8"))
        item = session["items"][local_id]
        self.assertEqual(item["status"], "CLOSED")
        self.assertTrue(item["handled"])
        self.assertEqual(item["decision"], "accept")

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
        self.assertIn("--repo and --pr are required", result.stderr)
