import importlib.util
import gzip
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

from tests.helpers import (
    PYTHON_COMMON_PY,
    PythonScriptTestCase,
    SUBMIT_FEEDBACK_PY,
)


class AuxiliaryScriptsTest(PythonScriptTestCase):
    def _load_python_common_module(self):
        spec = importlib.util.spec_from_file_location("python_common_module", PYTHON_COMMON_PY)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _wait_until(self, predicate, *, timeout=1.0, interval=0.01):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return predicate()

    def test_native_findings_parser_reports_invalid_json_array(self):
        from gh_address_cr.intake.findings import FindingsFormatError, parse_records

        with self.assertRaises(FindingsFormatError) as ctx:
            parse_records('[{"title": "oops"')
        self.assertIn("Invalid NDJSON input on line 1", str(ctx.exception))

    def test_native_findings_parser_reports_invalid_ndjson_line(self):
        from gh_address_cr.intake.findings import FindingsFormatError, parse_records

        with self.assertRaises(FindingsFormatError) as ctx:
            parse_records('{"title": "ok"}\nnot-json\n')
        self.assertIn("Invalid NDJSON input on line 2", str(ctx.exception))

    def test_submit_feedback_dry_run_outputs_canonical_issue_body(self):
        result = self.run_cmd(
            [
                sys.executable,
                str(SUBMIT_FEEDBACK_PY),
                "--dry-run",
                "--category",
                "workflow-gap",
                "--title",
                "review command left an ambiguous blocked state",
                "--summary",
                "The skill did not explain which step should happen next.",
                "--expected",
                "The skill should tell the agent which command or artifact to inspect next.",
                "--actual",
                "The run stopped with a blocked status and no actionable recovery path.",
                "--source-command",
                "gh-address-cr review octo/example 77",
                "--failing-command",
                "gh-address-cr final-gate octo/example 77",
                "--exit-code",
                "5",
                "--status",
                "BLOCKED",
                "--reason-code",
                "WAITING_FOR_FIX",
                "--waiting-on",
                "human_fix",
                "--run-id",
                "cr-loop-20260417T120000Z",
                "--skill-version",
                "1.2.0",
                "--using-repo",
                "octo/example",
                "--using-pr",
                "77",
                "--artifact",
                "/Users/snow/Documents/GitHub/gh-address-cr-skill/tmp/pr-77/blocker.json",
                "--notes",
                "Happened after the second retry.",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["target_repo"], "RbBtSn0w/gh-address-cr")
        self.assertTrue(payload["title"].startswith("[AI Feedback] "))
        self.assertIn("## Summary", payload["body"])
        self.assertIn("## Category", payload["body"])
        self.assertIn("workflow-gap", payload["body"])
        self.assertIn("## Expected Workflow", payload["body"])
        self.assertIn("## Actual Behavior", payload["body"])
        self.assertIn("## Reproduction Context", payload["body"])
        self.assertIn("## Technical Diagnostics", payload["body"])
        self.assertIn("`gh-address-cr review octo/example 77`", payload["body"])
        self.assertIn("`gh-address-cr final-gate octo/example 77`", payload["body"])
        self.assertIn("- Exit code: `5`", payload["body"])
        self.assertIn("- Status: `BLOCKED`", payload["body"])
        self.assertIn("- Reason code: `WAITING_FOR_FIX`", payload["body"])
        self.assertIn("- Waiting on: `human_fix`", payload["body"])
        self.assertIn("- Run ID: `cr-loop-20260417T120000Z`", payload["body"])
        self.assertIn("- Skill version: `1.2.0`", payload["body"])
        self.assertIn("`.../tmp/pr-77/blocker.json`", payload["body"])
        self.assertNotIn("/Users/snow", payload["body"])
        self.assertIn("## Additional Notes", payload["body"])

    def test_submit_feedback_sanitizes_title_and_artifacts_in_dry_run(self):
        result = self.run_cmd(
            [
                sys.executable,
                str(SUBMIT_FEEDBACK_PY),
                "--dry-run",
                "--category",
                "tooling-bug",
                "--title",
                "/Users/snow/private ghp_abcdefghijklmnopqrstuvwxyz12 alice@example.com",
                "--summary",
                "summary",
                "--expected",
                "expected",
                "--actual",
                "actual",
                "--artifact",
                "https://example.com/log?token=ghp_abcdefghijklmnopqrstuvwxyz12&owner=alice@example.com",
                "--artifact",
                "/Users/snow/Documents/GitHub/gh-address-cr-skill/tmp/state.json",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "dry-run")
        self.assertTrue(payload["title"].startswith("[AI Feedback] "))
        self.assertNotIn("/Users/snow/private", payload["title"])
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz12", payload["title"])
        self.assertNotIn("alice@example.com", payload["title"])
        self.assertIn("[redacted-token]", payload["title"])
        self.assertIn("[redacted-email]", payload["title"])
        self.assertIn("https://example.com/log?token=[redacted-token]&owner=[redacted-email]", payload["body"])
        self.assertIn("`.../gh-address-cr-skill/tmp/state.json`", payload["body"])

    def test_submit_feedback_sanitizes_agent_name_in_dry_run(self):
        result = self.run_cmd(
            [
                sys.executable,
                str(SUBMIT_FEEDBACK_PY),
                "--dry-run",
                "--category",
                "tooling-bug",
                "--agent",
                "/Users/snow/private ghp_abcdefghijklmnopqrstuvwxyz12 alice@example.com",
                "--title",
                "agent redaction",
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
        self.assertIn("- Agent: `.../private [redacted-token] [redacted-email]`", payload["body"])
        self.assertNotIn("/Users/snow/private", payload["body"])
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz12", payload["body"])
        self.assertNotIn("alice@example.com", payload["body"])

    def test_submit_feedback_sanitizes_review_context_fields_in_dry_run(self):
        result = self.run_cmd(
            [
                sys.executable,
                str(SUBMIT_FEEDBACK_PY),
                "--dry-run",
                "--category",
                "workflow-gap",
                "--title",
                "review context redaction",
                "--summary",
                "summary",
                "--expected",
                "expected",
                "--actual",
                "actual",
                "--using-repo",
                "/Users/snow/private ghp_abcdefghijklmnopqrstuvwxyz12",
                "--using-pr",
                "alice@example.com",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("- Repository under review: `.../private [redacted-token]`", payload["body"])
        self.assertIn("- Pull request under review: `[redacted-email]`", payload["body"])
        self.assertNotIn("/Users/snow/private", payload["body"])
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz12", payload["body"])
        self.assertNotIn("alice@example.com", payload["body"])

    def test_submit_feedback_infers_review_context_from_source_command_when_missing(self):
        result = self.run_cmd(
            [
                sys.executable,
                str(SUBMIT_FEEDBACK_PY),
                "--dry-run",
                "--category",
                "workflow-gap",
                "--title",
                "infer review context",
                "--summary",
                "summary",
                "--expected",
                "expected",
                "--actual",
                "actual",
                "--source-command",
                "python3 scripts/cli.py review octo/example 77",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("- Repository under review: `octo/example`", payload["body"])
        self.assertIn("- Pull request under review: `77`", payload["body"])

    def test_submit_feedback_does_not_infer_review_context_from_script_path_tokens(self):
        result = self.run_cmd(
            [
                sys.executable,
                str(SUBMIT_FEEDBACK_PY),
                "--dry-run",
                "--category",
                "workflow-gap",
                "--title",
                "ignore script path token",
                "--summary",
                "summary",
                "--expected",
                "expected",
                "--actual",
                "actual",
                "--source-command",
                "python3 scripts/cli.py 123",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("- Repository under review: Not provided.", payload["body"])
        self.assertIn("- Pull request under review: Not provided.", payload["body"])

    def test_submit_feedback_posts_issue_via_github_api(self):
        gh = self.bin_dir / "gh"
        request_path = Path(self.temp_dir.name) / "issue_request.json"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

request_path = Path({str(request_path)!r})
args = sys.argv[1:]
if len(args) >= 2 and args[0] == 'api' and args[1].startswith('search/issues?q=repo%3ARbBtSn0w%2Fgh-address-cr+') and args[1].endswith('&per_page=10'):
    print(json.dumps({{'items': []}}))
elif args[:4] == ['api', 'repos/RbBtSn0w/gh-address-cr/issues', '--method', 'POST']:
    payload = json.load(sys.stdin)
    request_path.write_text(json.dumps(payload), encoding='utf-8')
    print(json.dumps({{'number': 321, 'html_url': 'https://github.com/RbBtSn0w/gh-address-cr/issues/321'}}))
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(SUBMIT_FEEDBACK_PY),
                "--category",
                "tooling-bug",
                "--title",
                "submit feedback should create a GitHub issue",
                "--summary",
                "Need a structured feedback issue for the skill.",
                "--expected",
                "A new issue should be created in the skill repo.",
                "--actual",
                "The agent had no standardized place to report the problem.",
                "--failing-command",
                "gh-address-cr control-plane mixed json octo/example 77",
                "--exit-code",
                "2",
                "--status",
                "FAILED",
                "--reason-code",
                "INVALID_PRODUCER_OUTPUT",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["issue_number"], 321)
        self.assertEqual(
            payload["issue_url"],
            "https://github.com/RbBtSn0w/gh-address-cr/issues/321",
        )
        issue_request = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertTrue(issue_request["title"].startswith("[AI Feedback] "))
        self.assertIn("## Summary", issue_request["body"])
        self.assertIn("## Actual Behavior", issue_request["body"])
        self.assertIn("## Technical Diagnostics", issue_request["body"])
        self.assertIn("INVALID_PRODUCER_OUTPUT", issue_request["body"])
        self.assertIn("tooling-bug", issue_request["body"])
        self.assertNotIn("/Users/snow", issue_request["body"])

    def test_submit_feedback_auto_collects_workspace_evidence_without_user_paths(self):
        workspace = self.workspace_dir()
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "last-machine-summary.json").write_text(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason_code": "WAITING_FOR_FIX",
                    "waiting_on": "human_fix",
                    "exit_code": 5,
                    "item_id": "github-thread:THREAD_9",
                    "artifact_path": "/Users/snow/Documents/GitHub/gh-address-cr-skill/tmp/loop-request.json",
                }
            ),
            encoding="utf-8",
        )
        (workspace / "session.json").write_text(
            json.dumps(
                {
                    "status": "ACTIVE",
                    "metrics": {
                        "blocking_items_count": 2,
                        "open_local_findings_count": 1,
                        "unresolved_github_threads_count": 1,
                        "needs_human_items_count": 1,
                    },
                    "loop_state": {
                        "run_id": "run-777",
                        "status": "BLOCKED",
                        "current_item_id": "github-thread:THREAD_9",
                        "last_error": "Internal fixer action required: /Users/snow/Documents/GitHub/gh-address-cr-skill/tmp/loop-request.json",
                    },
                }
            ),
            encoding="utf-8",
        )
        (workspace / "audit_summary.md").write_text("summary", encoding="utf-8")
        (workspace / "github_pr_cache.json").write_text(json.dumps({"head_sha": "cafebabe"}), encoding="utf-8")

        result = self.run_cmd(
            [
                sys.executable,
                str(SUBMIT_FEEDBACK_PY),
                "--dry-run",
                "--category",
                "workflow-gap",
                "--title",
                "auto evidence should be collected",
                "--summary",
                "The script should absorb recent technical context automatically.",
                "--expected",
                "Feedback should include recent run evidence.",
                "--actual",
                "Operators currently have to add every diagnostic field manually.",
                "--using-repo",
                self.repo,
                "--using-pr",
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("- Exit code: `5`", payload["body"])
        self.assertIn("- Status: `BLOCKED`", payload["body"])
        self.assertIn("- Reason code: `WAITING_FOR_FIX`", payload["body"])
        self.assertIn("- Waiting on: `human_fix`", payload["body"])
        self.assertIn("- Run ID: `run-777`", payload["body"])
        self.assertIn("- Head SHA: `cafebabe`", payload["body"])
        self.assertIn("- Current item ID: `github-thread:THREAD_9`", payload["body"])
        self.assertIn("- Session blocking items: `2`", payload["body"])
        self.assertIn("- Audit summary SHA256:", payload["body"])
        self.assertIn("loop-request.json", payload["body"])
        self.assertNotIn("/Users/snow", payload["body"])

    def test_submit_feedback_reuses_existing_open_issue_for_same_fingerprint(self):
        gh = self.bin_dir / "gh"
        calls_path = Path(self.temp_dir.name) / "gh_calls.json"
        gh.write_text(
            f"""#!/usr/bin/env python3
import hashlib
import json
import sys
from pathlib import Path

calls_path = Path({str(calls_path)!r})
calls = json.loads(calls_path.read_text(encoding='utf-8')) if calls_path.exists() else []
args = sys.argv[1:]
calls.append(args)
calls_path.write_text(json.dumps(calls), encoding='utf-8')
fingerprint_payload = {{
    'category': 'workflow-gap',
    'title': '[AI Feedback] duplicate feedback',
    'summary': 'Same summary',
    'expected': 'Same expected',
    'actual': 'Same actual',
    'source_command': '',
    'failing_command': '',
}}
fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
if len(args) >= 2 and args[0] == 'api' and args[1] == f'search/issues?q=repo%3ARbBtSn0w%2Fgh-address-cr+is%3Aissue+{{fingerprint}}+in%3Abody&per_page=10':
    print(json.dumps({{'items': [{{'number': 88, 'html_url': 'https://github.com/RbBtSn0w/gh-address-cr/issues/88', 'state': 'open', 'body': f'<!-- gh-address-cr-feedback-fingerprint: {{fingerprint}} -->'}}]}}))
elif args[:4] == ['api', 'repos/RbBtSn0w/gh-address-cr/issues', '--method', 'POST']:
    raise SystemExit('create should not be called')
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(SUBMIT_FEEDBACK_PY),
                "--category",
                "workflow-gap",
                "--title",
                "duplicate feedback",
                "--summary",
                "Same summary",
                "--expected",
                "Same expected",
                "--actual",
                "Same actual",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "duplicate")
        self.assertEqual(payload["issue_number"], 88)
        calls = json.loads(calls_path.read_text(encoding="utf-8"))
        self.assertFalse(
            any(call[:4] == ["api", "repos/RbBtSn0w/gh-address-cr/issues", "--method", "POST"] for call in calls)
        )
        self.assertTrue(
            any(
                call[:2]
                == [
                    "api",
                    f"search/issues?q=repo%3ARbBtSn0w%2Fgh-address-cr+is%3Aissue+{payload['fingerprint']}+in%3Abody&per_page=10",
                ]
                for call in calls
            )
        )

    def test_submit_feedback_writes_local_audit_event(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:4] == ['api', 'repos/RbBtSn0w/gh-address-cr/issues', '--method', 'POST']:
    print(json.dumps({'number': 322, 'html_url': 'https://github.com/RbBtSn0w/gh-address-cr/issues/322'}))
elif len(args) >= 2 and args[0] == 'api' and args[1].startswith('search/issues?q=repo%3ARbBtSn0w%2Fgh-address-cr+') and args[1].endswith('&per_page=10'):
    print(json.dumps({'items': []}))
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        result = self.run_cmd(
            [
                sys.executable,
                str(SUBMIT_FEEDBACK_PY),
                "--category",
                "tooling-bug",
                "--title",
                "audit feedback submission",
                "--summary",
                "Need an audit trail for feedback submissions.",
                "--expected",
                "A local audit event should be written.",
                "--actual",
                "Feedback submission currently has no local audit record.",
                "--using-repo",
                self.repo,
                "--using-pr",
                self.pr,
                "--audit-id",
                "feedback-audit-1",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        audit_rows = [
            json.loads(line) for line in self.audit_log_file().read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        self.assertTrue(audit_rows)
        last = audit_rows[-1]
        self.assertEqual(last["action"], "submit_feedback")
        self.assertEqual(last["status"], "ok")
        self.assertEqual(last["audit_id"], "feedback-audit-1")
