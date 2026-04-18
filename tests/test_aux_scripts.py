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
    BATCH_RESOLVE_PY,
    CLEAN_STATE_PY,
    GENERATE_REPLY_PY,
    PYTHON_COMMON_PY,
    PythonScriptTestCase,
    RUN_ONCE_PY,
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

    def test_run_once_helper_parses_each_snapshot_line_once(self):
        spec = importlib.util.spec_from_file_location("run_once_module", RUN_ONCE_PY)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(PYTHON_COMMON_PY.parent))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        snapshot_text = '\n'.join(
            [
                '{"id":"THREAD_1","isResolved":false}',
                '{"id":"THREAD_2","isResolved":true}',
                '{"id":"THREAD_3","isResolved":false}',
                "",
            ]
        )
        self.assertEqual(module.unresolved_ids_from_snapshot_text(snapshot_text), ["THREAD_1", "THREAD_3"])

    def test_ingest_findings_reports_invalid_json_array(self):
        ingest_spec = importlib.util.spec_from_file_location("ingest_findings_module", PYTHON_COMMON_PY.parent / "ingest_findings.py")
        self.assertIsNotNone(ingest_spec)
        ingest_module = importlib.util.module_from_spec(ingest_spec)
        sys.path.insert(0, str(PYTHON_COMMON_PY.parent))
        try:
            ingest_spec.loader.exec_module(ingest_module)
        finally:
            sys.path.pop(0)

        with self.assertRaises(SystemExit) as ctx:
            ingest_module.parse_records('[{"title": "oops"')
        self.assertIn("Invalid JSON array input", str(ctx.exception))

    def test_ingest_findings_reports_invalid_ndjson_line(self):
        ingest_spec = importlib.util.spec_from_file_location("ingest_findings_module", PYTHON_COMMON_PY.parent / "ingest_findings.py")
        self.assertIsNotNone(ingest_spec)
        ingest_module = importlib.util.module_from_spec(ingest_spec)
        sys.path.insert(0, str(PYTHON_COMMON_PY.parent))
        try:
            ingest_spec.loader.exec_module(ingest_module)
        finally:
            sys.path.pop(0)

        with self.assertRaises(SystemExit) as ctx:
            ingest_module.parse_records('{"title": "ok"}\nnot-json\n')
        self.assertIn("Invalid NDJSON input on line 2", str(ctx.exception))

    def test_generate_reply_fix_mode_writes_markdown(self):
        output = Path(self.temp_dir.name) / "reply.md"
        result = self.run_cmd(
            [
                sys.executable,
                str(GENERATE_REPLY_PY),
                "--severity",
                "P1",
                str(output),
                "abc123",
                "src/a.py, src/b.py",
                "pytest",
                "passed",
                "Fixed the root cause.",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        body = output.read_text(encoding="utf-8")
        self.assertIn("Fixed in `abc123`.", body)
        self.assertIn("- `src/a.py`: updated per CR scope", body)
        self.assertIn("- Fixed the root cause.", body)

    def test_generate_reply_rejects_invalid_severity(self):
        output = Path(self.temp_dir.name) / "reply.md"
        result = self.run_cmd(
            [
                sys.executable,
                str(GENERATE_REPLY_PY),
                "--severity",
                "P9",
                str(output),
                "abc123",
                "src/a.py",
                "pytest",
                "passed",
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid severity", result.stderr)

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
                "python3 /Users/snow/Documents/GitHub/gh-address-cr-skill/gh-address-cr/scripts/cli.py review octo/example 77",
                "--failing-command",
                "python3 /Users/snow/Documents/GitHub/gh-address-cr-skill/gh-address-cr/scripts/final_gate.py octo/example 77",
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
        self.assertEqual(payload["target_repo"], "RbBtSn0w/gh-address-cr-skill")
        self.assertTrue(payload["title"].startswith("[AI Feedback] "))
        self.assertIn("## Summary", payload["body"])
        self.assertIn("## Category", payload["body"])
        self.assertIn("workflow-gap", payload["body"])
        self.assertIn("## Expected Workflow", payload["body"])
        self.assertIn("## Actual Behavior", payload["body"])
        self.assertIn("## Reproduction Context", payload["body"])
        self.assertIn("## Technical Diagnostics", payload["body"])
        self.assertIn("`python3 .../gh-address-cr/scripts/cli.py review octo/example 77`", payload["body"])
        self.assertIn("`python3 .../gh-address-cr/scripts/final_gate.py octo/example 77`", payload["body"])
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
if len(args) >= 2 and args[0] == 'api' and args[1].startswith('search/issues?q=repo%3ARbBtSn0w%2Fgh-address-cr-skill+') and args[1].endswith('&per_page=10'):
    print(json.dumps({{'items': []}}))
elif args[:4] == ['api', 'repos/RbBtSn0w/gh-address-cr-skill/issues', '--method', 'POST']:
    payload = json.load(sys.stdin)
    request_path.write_text(json.dumps(payload), encoding='utf-8')
    print(json.dumps({{'number': 321, 'html_url': 'https://github.com/RbBtSn0w/gh-address-cr-skill/issues/321'}}))
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
                "python3 /Users/snow/Documents/GitHub/gh-address-cr-skill/gh-address-cr/scripts/control_plane.py mixed json octo/example 77",
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
            "https://github.com/RbBtSn0w/gh-address-cr-skill/issues/321",
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
if len(args) >= 2 and args[0] == 'api' and args[1] == f'search/issues?q=repo%3ARbBtSn0w%2Fgh-address-cr-skill+is%3Aissue+{{fingerprint}}+in%3Abody&per_page=10':
    print(json.dumps({{'items': [{{'number': 88, 'html_url': 'https://github.com/RbBtSn0w/gh-address-cr-skill/issues/88', 'state': 'open', 'body': f'<!-- gh-address-cr-feedback-fingerprint: {{fingerprint}} -->'}}]}}))
elif args[:4] == ['api', 'repos/RbBtSn0w/gh-address-cr-skill/issues', '--method', 'POST']:
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
        self.assertFalse(any(call[:4] == ["api", "repos/RbBtSn0w/gh-address-cr-skill/issues", "--method", "POST"] for call in calls))
        self.assertTrue(any(call[:2] == ["api", f"search/issues?q=repo%3ARbBtSn0w%2Fgh-address-cr-skill+is%3Aissue+{payload['fingerprint']}+in%3Abody&per_page=10"] for call in calls))

    def test_submit_feedback_writes_local_audit_event(self):
        gh = self.bin_dir / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:4] == ['api', 'repos/RbBtSn0w/gh-address-cr-skill/issues', '--method', 'POST']:
    print(json.dumps({'number': 322, 'html_url': 'https://github.com/RbBtSn0w/gh-address-cr-skill/issues/322'}))
elif len(args) >= 2 and args[0] == 'api' and args[1].startswith('search/issues?q=repo%3ARbBtSn0w%2Fgh-address-cr-skill+') and args[1].endswith('&per_page=10'):
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
        audit_rows = [json.loads(line) for line in self.audit_log_file().read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertTrue(audit_rows)
        last = audit_rows[-1]
        self.assertEqual(last["action"], "submit_feedback")
        self.assertEqual(last["status"], "ok")
        self.assertEqual(last["audit_id"], "feedback-audit-1")

    def test_batch_resolve_python_processes_approved_lines(self):
        approved = Path(self.temp_dir.name) / "approved.txt"
        approved.write_text("# comment\nAPPROVED THREAD_1\n\nAPPROVED THREAD_2\n", encoding="utf-8")
        result = self.run_cmd(
            [
                sys.executable,
                str(BATCH_RESOLVE_PY),
                "--dry-run",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                str(approved),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[dry-run] Would resolve thread: THREAD_1", result.stdout)
        self.assertIn("[dry-run] Would resolve thread: THREAD_2", result.stdout)

    def test_batch_resolve_requires_explicit_repo_and_pr(self):
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

        approved = Path(self.temp_dir.name) / "approved.txt"
        approved.write_text("APPROVED THREAD_1\n", encoding="utf-8")
        result = self.run_cmd([sys.executable, str(BATCH_RESOLVE_PY), "--dry-run", str(approved)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--repo and --pr are required", result.stderr)

    def test_python_common_gh_read_cmd_retries_transient_failure(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_retry_state.json"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file.as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"calls": 0}}))

payload = json.loads(state_file.read_text())
payload["calls"] += 1
state_file.write_text(json.dumps(payload))
if payload["calls"] == 1:
    sys.stderr.write("graphql error\\n")
    raise SystemExit(1)
print(json.dumps({{"data": {{"ok": True}}}}))
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        spec = importlib.util.spec_from_file_location("python_common_module", PYTHON_COMMON_PY)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin_dir}:{original_path}"
        try:
            spec.loader.exec_module(module)
            result = module.gh_read_cmd(["gh", "api", "graphql"])
        finally:
            os.environ["PATH"] = original_path

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["calls"], 2)

    def test_python_common_gh_write_cmd_does_not_retry_transient_failure(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_write_state.json"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file.as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"calls": 0}}))

payload = json.loads(state_file.read_text())
payload["calls"] += 1
state_file.write_text(json.dumps(payload))
sys.stderr.write("graphql error\\n")
raise SystemExit(1)
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        spec = importlib.util.spec_from_file_location("python_common_module", PYTHON_COMMON_PY)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin_dir}:{original_path}"
        try:
            spec.loader.exec_module(module)
            result = module.gh_write_cmd(["gh", "api", "graphql"], check=False)
        finally:
            os.environ["PATH"] = original_path

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["calls"], 1)

    def test_python_common_run_cmd_retries_transient_gh_failure_when_requested(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_run_cmd_retry_state.json"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file.as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"calls": 0}}))

payload = json.loads(state_file.read_text())
payload["calls"] += 1
state_file.write_text(json.dumps(payload))
if payload["calls"] == 1:
    sys.stderr.write("graphql failed\\n")
    raise SystemExit(1)
print("ok")
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        spec = importlib.util.spec_from_file_location("python_common_module", PYTHON_COMMON_PY)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin_dir}:{original_path}"
        try:
            spec.loader.exec_module(module)
            result = module.run_cmd(["gh", "api", "graphql"], retries=2)
        finally:
            os.environ["PATH"] = original_path

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["calls"], 2)

    def test_python_common_pull_request_read_cache_reuses_files_for_same_head(self):
        original_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        try:
            module = self._load_python_common_module()
            cache = module.PullRequestReadCache(self.repo, self.pr)
            calls = {"count": 0}

            def loader():
                calls["count"] += 1
                return [{"filename": "src/example.py"}]

            first = cache.get_or_load_files("deadbeef", loader)
            second = cache.get_or_load_files("deadbeef", loader)
        finally:
            if original_state_dir is None:
                os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
            else:
                os.environ["GH_ADDRESS_CR_STATE_DIR"] = original_state_dir

        self.assertEqual(first, [{"filename": "src/example.py"}])
        self.assertEqual(second, first)
        self.assertEqual(calls["count"], 1)

    def test_python_common_pull_request_read_cache_replaces_files_when_head_changes(self):
        original_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        try:
            module = self._load_python_common_module()
            cache = module.PullRequestReadCache(self.repo, self.pr)
            calls = {"count": 0}

            def load_first():
                calls["count"] += 1
                return [{"filename": "src/first.py"}]

            def load_second():
                calls["count"] += 1
                return [{"filename": "src/second.py"}]

            cache.get_or_load_files("deadbeef", load_first)
            second = cache.get_or_load_files("cafebabe", load_second)
            cache_path = module.github_pr_cache_file(self.repo, self.pr)
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        finally:
            if original_state_dir is None:
                os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
            else:
                os.environ["GH_ADDRESS_CR_STATE_DIR"] = original_state_dir

        self.assertEqual(second, [{"filename": "src/second.py"}])
        self.assertEqual(calls["count"], 2)
        self.assertEqual(payload["head_sha"], "cafebabe")
        self.assertEqual(payload["files_by_head"], {"cafebabe": [{"filename": "src/second.py"}]})

    def test_python_common_threads_snapshot_helpers_round_trip_rows(self):
        original_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        try:
            module = self._load_python_common_module()
            rows = [
                {"id": "THREAD_1", "isResolved": False, "path": "src/a.py", "line": 1},
                {"id": "THREAD_2", "isResolved": True, "path": "src/b.py", "line": 2},
            ]
            snapshot = module.write_threads_snapshot(self.repo, self.pr, rows)
            loaded = module.load_threads_snapshot_rows(snapshot)
        finally:
            if original_state_dir is None:
                os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
            else:
                os.environ["GH_ADDRESS_CR_STATE_DIR"] = original_state_dir

        self.assertEqual(loaded, rows)

    def test_python_common_copy_threads_snapshot_reuses_existing_snapshot_text(self):
        original_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        try:
            module = self._load_python_common_module()
            source = Path(self.temp_dir.name) / "source_snapshot.jsonl"
            source.write_text(
                '{"id":"THREAD_1","isResolved":false,"path":"src/a.py","line":1}\n',
                encoding="utf-8",
            )
            copied = module.copy_threads_snapshot(self.repo, self.pr, source)
            loaded = module.load_threads_snapshot_rows(copied)
        finally:
            if original_state_dir is None:
                os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
            else:
                os.environ["GH_ADDRESS_CR_STATE_DIR"] = original_state_dir

        self.assertEqual(loaded, [{"id": "THREAD_1", "isResolved": False, "path": "src/a.py", "line": 1}])

    def test_python_common_trace_event_exports_otlp_http_json_via_base_endpoint(self):
        original_env = os.environ.copy()
        captured: list[dict] = []

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(request, timeout):
            captured.append(
                {
                    "url": request.full_url,
                    "headers": dict(request.header_items()),
                    "data": request.data,
                    "timeout": timeout,
                }
            )
            return DummyResponse()

        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        os.environ["OTEL_SERVICE_NAME"] = "gh-address-cr-cli"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://worker.example/collector"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/json"
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "authorization=Bearer%20worker-secret,x-gh-address-cr-key=abc123"
        os.environ["OTEL_RESOURCE_ATTRIBUTES"] = "deployment.environment=test"
        try:
            module = self._load_python_common_module()
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                module.trace_event(
                    "run_once",
                    "start",
                    self.repo,
                    self.pr,
                    run_id="run-123",
                    audit_id="audit-123",
                    message="Starting triage snapshot",
                    details={"attempt": 1},
                )
                self.assertTrue(self._wait_until(lambda: len(captured) == 1))
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual(request["url"], "https://worker.example/collector/v1/logs")
        self.assertEqual(request["headers"]["Content-type"], "application/json")
        self.assertEqual(request["headers"]["Content-encoding"], "gzip")
        self.assertEqual(request["headers"]["Authorization"], "Bearer worker-secret")
        self.assertEqual(request["headers"]["X-gh-address-cr-key"], "abc123")
        payload = json.loads(gzip.decompress(request["data"]).decode("utf-8"))
        resource_logs = payload["resourceLogs"]
        self.assertEqual(len(resource_logs), 1)
        resource_attributes = {
            item["key"]: next(iter(item["value"].values()))
            for item in resource_logs[0]["resource"]["attributes"]
        }
        self.assertEqual(resource_attributes["service.name"], "gh-address-cr-cli")
        self.assertEqual(resource_attributes["deployment.environment"], "test")
        log_record = resource_logs[0]["scopeLogs"][0]["logRecords"][0]
        self.assertEqual(log_record["body"]["stringValue"], "Starting triage snapshot")
        record_attributes = {
            item["key"]: next(iter(item["value"].values()))
            for item in log_record["attributes"]
        }
        self.assertEqual(record_attributes["gh.address_cr.log_kind"], "trace")
        self.assertEqual(record_attributes["gh.address_cr.action"], "run_once")
        self.assertEqual(record_attributes["gh.address_cr.status"], "start")
        self.assertEqual(record_attributes["gh.address_cr.repo"], self.repo)
        self.assertEqual(record_attributes["gh.address_cr.pr"], self.pr)
        self.assertEqual(record_attributes["gh.address_cr.run_id"], "run-123")
        self.assertEqual(record_attributes["gh.address_cr.audit_id"], "audit-123")

    def test_python_common_trace_event_exports_to_public_relay_by_default(self):
        original_env = os.environ.copy()
        captured: list[dict] = []

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(request, timeout):
            captured.append(
                {
                    "url": request.full_url,
                    "headers": dict(request.header_items()),
                    "timeout": timeout,
                }
            )
            return DummyResponse()

        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        for key in (
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
            "OTEL_RESOURCE_ATTRIBUTES",
            "OTEL_SERVICE_NAME",
        ):
            os.environ.pop(key, None)
        try:
            module = self._load_python_common_module()
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                module.trace_event("review", "ok", self.repo, self.pr, message="Handled threads")
                self.assertTrue(self._wait_until(lambda: len(captured) == 1))
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual(request["url"], "https://gh-address-cr.hamiltonsnow.workers.dev/v1/logs")
        self.assertEqual(request["headers"]["Content-type"], "application/json")
        self.assertEqual(request["headers"]["Content-encoding"], "gzip")
        self.assertNotIn("Authorization", request["headers"])

    def test_python_common_trace_event_skips_otlp_export_when_disabled_by_env(self):
        original_env = os.environ.copy()
        captured: list[dict] = []

        def fake_urlopen(request, timeout):
            captured.append({"url": request.full_url, "timeout": timeout})
            raise AssertionError("OTLP export should be disabled")

        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        os.environ["GH_ADDRESS_CR_DISABLE_OTLP_EXPORT"] = "1"
        for key in (
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
            "OTEL_RESOURCE_ATTRIBUTES",
            "OTEL_SERVICE_NAME",
        ):
            os.environ.pop(key, None)
        try:
            module = self._load_python_common_module()
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                module.trace_event("review", "ok", self.repo, self.pr, message="Handled threads")
                time.sleep(0.05)
            trace_rows = [
                json.loads(line)
                for line in module.trace_log_file(self.repo, self.pr).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(captured, [])
        self.assertEqual(len(trace_rows), 1)
        self.assertEqual(trace_rows[0]["action"], "review")

    def test_python_common_trace_event_uses_logs_endpoint_as_is(self):
        original_env = os.environ.copy()
        captured: list[dict] = []

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(request, timeout):
            captured.append(
                {
                    "url": request.full_url,
                    "headers": dict(request.header_items()),
                    "timeout": timeout,
                }
            )
            return DummyResponse()

        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        os.environ["OTEL_SERVICE_NAME"] = "gh-address-cr-cli"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://worker.example/base"
        os.environ["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"] = "https://worker.example/custom/logs"
        os.environ["OTEL_EXPORTER_OTLP_LOGS_PROTOCOL"] = "http/json"
        os.environ["OTEL_EXPORTER_OTLP_LOGS_HEADERS"] = "x-otlp-route=logs-only"
        try:
            module = self._load_python_common_module()
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                module.trace_event("final_gate", "ok", self.repo, self.pr, message="Gate passed")
                self.assertTrue(self._wait_until(lambda: len(captured) == 1))
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["url"], "https://worker.example/custom/logs")
        self.assertEqual(captured[0]["headers"]["X-otlp-route"], "logs-only")

    def test_python_common_trace_event_records_local_diagnostic_when_telemetry_export_fails(self):
        original_env = os.environ.copy()

        def failing_urlopen(_request, timeout=None):
            _ = timeout
            raise OSError("worker unavailable")

        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        os.environ["OTEL_SERVICE_NAME"] = "gh-address-cr-cli"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://worker.example/base"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/json"
        try:
            module = self._load_python_common_module()
            with patch("urllib.request.urlopen", side_effect=failing_urlopen):
                module.trace_event("review", "ok", self.repo, self.pr, message="Handled threads")
                self.assertTrue(
                    self._wait_until(
                        lambda: module.trace_log_file(self.repo, self.pr).exists()
                        and len(
                            [
                                line
                                for line in module.trace_log_file(self.repo, self.pr).read_text(encoding="utf-8").splitlines()
                                if line.strip()
                            ]
                        )
                        >= 2
                    )
                )
            trace_rows = [
                json.loads(line)
                for line in module.trace_log_file(self.repo, self.pr).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(trace_rows[0]["action"], "review")
        self.assertEqual(trace_rows[0]["message"], "Handled threads")
        self.assertEqual(trace_rows[1]["action"], "telemetry_export")
        self.assertEqual(trace_rows[1]["status"], "error")
        self.assertIn("worker unavailable", trace_rows[1]["message"])

    def test_python_common_trace_event_failure_diagnostic_uses_original_state_dir_after_env_changes(self):
        original_env = os.environ.copy()
        release_export = threading.Event()

        def delayed_failing_urlopen(_request, timeout=None):
            _ = timeout
            self.assertTrue(release_export.wait(1.0))
            raise OSError("worker unavailable")

        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        os.environ["OTEL_SERVICE_NAME"] = "gh-address-cr-cli"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://worker.example/base"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/json"
        try:
            module = self._load_python_common_module()
            expected_trace_file = module.trace_log_file(self.repo, self.pr)
            with patch("urllib.request.urlopen", side_effect=delayed_failing_urlopen):
                module.trace_event("review", "ok", self.repo, self.pr, message="Handled threads")
                os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
                release_export.set()
                self.assertTrue(
                    self._wait_until(
                        lambda: expected_trace_file.exists()
                        and len(
                            [
                                line
                                for line in expected_trace_file.read_text(encoding="utf-8").splitlines()
                                if line.strip()
                            ]
                        )
                        >= 2
                    )
                )
            trace_rows = [
                json.loads(line)
                for line in expected_trace_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(trace_rows[0]["action"], "review")
        self.assertEqual(trace_rows[1]["action"], "telemetry_export")
        self.assertIn("worker unavailable", trace_rows[1]["message"])

    def test_python_common_trace_event_failure_does_not_recreate_removed_workspace(self):
        original_env = os.environ.copy()
        release_export = threading.Event()

        def delayed_failing_urlopen(_request, timeout=None):
            _ = timeout
            self.assertTrue(release_export.wait(1.0))
            raise OSError("worker unavailable")

        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        os.environ["OTEL_SERVICE_NAME"] = "gh-address-cr-cli"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://worker.example/base"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/json"
        try:
            module = self._load_python_common_module()
            expected_trace_file = module.trace_log_file(self.repo, self.pr)
            workspace = expected_trace_file.parent
            with patch("urllib.request.urlopen", side_effect=delayed_failing_urlopen):
                module.trace_event("review", "ok", self.repo, self.pr, message="Handled threads")
                shutil.rmtree(workspace)
                release_export.set()
                self.assertTrue(self._wait_until(lambda: not workspace.exists()))
                time.sleep(0.05)
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        self.assertFalse(workspace.exists())

    def test_python_common_audit_event_keeps_local_contract_and_exports_audit_and_trace(self):
        original_env = os.environ.copy()
        exported_kinds: list[str] = []

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(request, timeout=None):
            _ = timeout
            payload = json.loads(gzip.decompress(request.data).decode("utf-8"))
            exported_kinds.append(
                payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"][0]["value"]["stringValue"]
            )
            return DummyResponse()

        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://worker.example/base"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/json"
        try:
            module = self._load_python_common_module()
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                module.audit_event("final_gate", "ok", self.repo, self.pr, "run-456", "Gate passed", {"count": 0})
                self.assertTrue(self._wait_until(lambda: len(exported_kinds) == 2))
            audit_rows = [
                json.loads(line)
                for line in module.audit_log_file(self.repo, self.pr).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            trace_rows = [
                json.loads(line)
                for line in module.trace_log_file(self.repo, self.pr).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(len(audit_rows), 1)
        self.assertEqual(audit_rows[0]["action"], "final_gate")
        self.assertEqual(len(trace_rows), 1)
        self.assertEqual(trace_rows[0]["action"], "final_gate")
        self.assertEqual(exported_kinds, ["audit", "trace"])

    def test_python_common_trace_event_sanitizes_exported_payload_for_hosted_relay(self):
        original_env = os.environ.copy()
        captured: list[dict] = []

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(request, timeout=None):
            _ = timeout
            captured.append(json.loads(gzip.decompress(request.data).decode("utf-8")))
            return DummyResponse()

        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        for key in (
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
            "OTEL_RESOURCE_ATTRIBUTES",
            "OTEL_SERVICE_NAME",
        ):
            os.environ.pop(key, None)
        try:
            module = self._load_python_common_module()
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                module.trace_event(
                    "post_reply",
                    "failed",
                    self.repo,
                    self.pr,
                    message="reply_file=/Users/snow/private/reply.md token=ghp_secretvalue alice@example.com",
                    details={
                        "reply_file": "/Users/snow/private/reply.md",
                        "error": "token=ghp_secretvalue email=alice@example.com",
                    },
                )
                self.assertTrue(self._wait_until(lambda: len(captured) == 1))
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        log_record = captured[0]["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        self.assertIn("[redacted-token]", log_record["body"]["stringValue"])
        self.assertIn("[redacted-email]", log_record["body"]["stringValue"])
        self.assertIn(".../private/reply.md", log_record["body"]["stringValue"])
        self.assertNotIn("/Users/snow/private", log_record["body"]["stringValue"])
        details_json = next(
            item["value"]["stringValue"]
            for item in log_record["attributes"]
            if item["key"] == "gh.address_cr.details_json"
        )
        self.assertIn("[redacted-token]", details_json)
        self.assertIn("[redacted-email]", details_json)
        self.assertIn(".../private/reply.md", details_json)
        self.assertNotIn("/Users/snow/private", details_json)
        self.assertNotIn("ghp_secretvalue", details_json)
        self.assertNotIn("alice@example.com", details_json)

    def test_python_common_trace_event_does_not_block_on_slow_telemetry_delivery(self):
        original_env = os.environ.copy()
        started = threading.Event()
        finished = threading.Event()

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        def slow_urlopen(_request, timeout=None):
            _ = timeout
            started.set()
            time.sleep(0.4)
            finished.set()
            return DummyResponse()

        os.environ["GH_ADDRESS_CR_STATE_DIR"] = str(self.state_dir)
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://worker.example/base"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/json"
        try:
            module = self._load_python_common_module()
            with patch("urllib.request.urlopen", side_effect=slow_urlopen):
                started_at = time.monotonic()
                module.trace_event("review", "ok", self.repo, self.pr, message="Handled threads")
                elapsed = time.monotonic() - started_at
                self.assertLess(elapsed, 0.2)
                self.assertTrue(started.wait(1.0))
                self.assertTrue(finished.wait(1.0))
        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_python_common_github_viewer_login_caches_value_within_process(self):
        gh = self.bin_dir / "gh"
        state_file = Path(self.temp_dir.name) / "gh_user_cache_state.json"
        gh.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_file = Path({str(state_file.as_posix())!r})
if not state_file.exists():
    state_file.write_text(json.dumps({{"calls": 0}}))

state = json.loads(state_file.read_text(encoding='utf-8'))
args = sys.argv[1:]
if args[:2] == ['api', 'user']:
    state['calls'] += 1
    state_file.write_text(json.dumps(state), encoding='utf-8')
    print(json.dumps({{"login": "tester"}}))
else:
    raise SystemExit(f'unhandled gh args: {{args}}')
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        module = self._load_python_common_module()
        original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin_dir}:{original_path}"
        try:
            first = module.github_viewer_login()
            second = module.github_viewer_login()
        finally:
            os.environ["PATH"] = original_path

        self.assertEqual(first, "tester")
        self.assertEqual(second, "tester")
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["calls"], 1)

    def test_batch_resolve_rejects_invalid_lines(self):
        approved = Path(self.temp_dir.name) / "approved.txt"
        approved.write_text("NOPE THREAD_1\n", encoding="utf-8")
        result = self.run_cmd(
            [
                sys.executable,
                str(BATCH_RESOLVE_PY),
                "--dry-run",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                str(approved),
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected format: APPROVED <thread_id>", result.stderr)

    def test_clean_state_removes_pr_scoped_files(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        session_file = self.session_file()
        audit_file = self.audit_log_file()
        summary_file = self.audit_summary_file()
        artifacts_dir = self.artifacts_dir()
        session_file.parent.mkdir(parents=True, exist_ok=True)
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text("{}", encoding="utf-8")
        audit_file.write_text("{}\n", encoding="utf-8")
        summary_file.write_text("summary", encoding="utf-8")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "request.json").write_text("{}", encoding="utf-8")

        result = self.run_cmd(
            [
                sys.executable,
                str(CLEAN_STATE_PY),
                "--repo",
                self.repo,
                "--pr",
                self.pr,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(session_file.exists())
        self.assertFalse(audit_file.exists())
        self.assertFalse(summary_file.exists())
        self.assertFalse(artifacts_dir.exists())

    def test_clean_state_accepts_legacy_clean_tmp_flag(self):
        result = self.run_cmd([sys.executable, str(CLEAN_STATE_PY), "--clean-tmp"])
        self.assertEqual(result.returncode, 0, result.stderr)
