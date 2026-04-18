import importlib.util
import io
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tests.helpers import PythonScriptTestCase, SCRIPTS_DIR


@contextmanager
def patched_argv(argv: list[str]):
    with patch.object(sys, "argv", argv):
        yield


class NetworkWriteContractTest(PythonScriptTestCase):
    def load_module(self, script_name: str, module_name: str):
        path = SCRIPTS_DIR / script_name
        sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def test_resolve_thread_reports_unknown_when_session_update_fails_after_remote_success(self):
        module = self.load_module("resolve_thread.py", "resolve_thread_under_test")

        module.gh_write_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            json.dumps(
                {
                    "data": {
                        "resolveReviewThread": {
                            "thread": {
                                "id": "THREAD_RESOLVE",
                                "isResolved": True,
                            }
                        }
                    }
                }
            ),
            "",
        )
        module.session_engine = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", "")
        module.append_handled = lambda *args, **kwargs: None
        module.audit_event = lambda *args, **kwargs: None

        def failing_run_cmd(*args, **kwargs):
            raise subprocess.CalledProcessError(7, args[0], "", "session update failed")

        module.run_cmd = failing_run_cmd

        with patched_argv(
            [
                "resolve_thread.py",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "THREAD_RESOLVE",
            ]
        ), patch("sys.stdout", new=io.StringIO()) as stdout, patch("sys.stderr", new=io.StringIO()) as stderr:
            rc = module.main()
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["status"], "unknown")
        self.assertEqual(payload["remote_status"], "succeeded")
        self.assertEqual(payload["session_status"], "failed")
        self.assertTrue(payload["resolved"])
        self.assertIn("session update failed", payload["error"])
        self.assertIn("session update failed", stderr.getvalue())

    def test_publish_finding_reports_unknown_when_mark_published_fails_after_comment_creation(self):
        module = self.load_module("publish_finding.py", "publish_finding_under_test")

        module.load_item = lambda *args, **kwargs: {
            "item_id": "local-finding:abc",
            "item_kind": "local_finding",
            "title": "Publish me",
            "body": "Body",
            "path": "src/a.py",
            "line": 4,
        }
        module.load_pull_request_head_sha = lambda *args, **kwargs: "deadbeef"
        module.load_pr_files = lambda *args, **kwargs: [{"filename": "src/a.py", "patch": "@@ -1,1 +1,4 @@\n line1\n+line2\n+line3\n+line4"}]
        module.audit_event = lambda *args, **kwargs: None
        module.gh_write_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            json.dumps({"id": 123, "html_url": "https://example.test/comment/123"}),
            "",
        )

        def failing_run_cmd(*args, **kwargs):
            raise subprocess.CalledProcessError(9, args[0], "", "mark-published failed")

        module.run_cmd = failing_run_cmd

        with patched_argv(
            [
                "publish_finding.py",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "local-finding:abc",
            ]
        ), patch("sys.stdout", new=io.StringIO()) as stdout, patch("sys.stderr", new=io.StringIO()) as stderr:
            rc = module.main()
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["status"], "unknown")
        self.assertEqual(payload["remote_status"], "succeeded")
        self.assertEqual(payload["session_status"], "failed")
        self.assertEqual(payload["comment_id"], 123)
        self.assertEqual(payload["comment_url"], "https://example.test/comment/123")
        self.assertIn("mark-published failed", payload["error"])
        self.assertIn("mark-published failed", stderr.getvalue())

    def test_post_reply_audits_invalid_json_response(self):
        module = self.load_module("post_reply.py", "post_reply_under_test")

        reply_file = Path(self.temp_dir.name) / "reply.md"
        reply_file.write_text("Reply body", encoding="utf-8")
        audits = []

        module.github_viewer_login = lambda: "tester"
        module.list_pending_review_ids = lambda *_args, **_kwargs: set()
        module.submit_pending_reviews_result = lambda *_args, **_kwargs: {"status": "skipped", "submitted": [], "error": None}
        module.audit_event = lambda *args, **kwargs: audits.append((args, kwargs))
        module.gh_write_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "not-json", "")

        with patched_argv(
            [
                "post_reply.py",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "THREAD_REPLY",
                str(reply_file),
            ]
        ), patch("sys.stdout", new=io.StringIO()) as stdout, patch("sys.stderr", new=io.StringIO()) as stderr:
            rc = module.main()
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "reply response was not valid JSON")
        self.assertTrue(audits)
        self.assertIn("reply response was not valid JSON", stderr.getvalue())

    def test_resolve_thread_audits_invalid_json_response(self):
        module = self.load_module("resolve_thread.py", "resolve_thread_under_test")

        audits = []
        module.gh_write_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "not-json", "")
        module.session_engine = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", "")
        module.audit_event = lambda *args, **kwargs: audits.append((args, kwargs))
        module.run_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", "")
        module.append_handled = lambda *args, **kwargs: None

        with patched_argv(
            [
                "resolve_thread.py",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "THREAD_RESOLVE",
            ]
        ), patch("sys.stdout", new=io.StringIO()) as stdout, patch("sys.stderr", new=io.StringIO()) as stderr:
            rc = module.main()
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "resolve response was not valid JSON")
        self.assertTrue(audits)
        self.assertIn("resolve response was not valid JSON", stderr.getvalue())

    def test_publish_finding_audits_invalid_json_response(self):
        module = self.load_module("publish_finding.py", "publish_finding_under_test")

        module.load_item = lambda *args, **kwargs: {
            "item_id": "local-finding:abc",
            "item_kind": "local_finding",
            "title": "Publish me",
            "body": "Body",
            "path": "src/a.py",
            "line": 4,
        }
        module.load_pull_request_head_sha = lambda *args, **kwargs: "deadbeef"
        module.load_pr_files = lambda *args, **kwargs: [{"filename": "src/a.py", "patch": "@@ -1,1 +1,4 @@\n line1\n+line2\n+line3\n+line4"}]
        audits = []
        module.audit_event = lambda *args, **kwargs: audits.append((args, kwargs))
        module.gh_write_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "not-json", "")

        with patched_argv(
            [
                "publish_finding.py",
                "--repo",
                self.repo,
                "--pr",
                self.pr,
                "local-finding:abc",
            ]
        ), patch("sys.stdout", new=io.StringIO()) as stdout, patch("sys.stderr", new=io.StringIO()) as stderr:
            rc = module.main()
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "publish response was not valid JSON")
        self.assertTrue(audits)
        self.assertIn("publish response was not valid JSON", stderr.getvalue())

    def test_submit_feedback_audits_invalid_json_response(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_under_test")

        audits = []
        module.audit_event = lambda *args, **kwargs: audits.append((args, kwargs))
        module.gh_read_json = lambda *args, **kwargs: {"items": []}
        module.gh_write_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "not-json", "")

        with patched_argv(
            [
                "submit_feedback.py",
                "--category",
                "tooling-bug",
                "--title",
                "bad response",
                "--summary",
                "summary",
                "--expected",
                "expected",
                "--actual",
                "actual",
            ]
        ), patch("sys.stdout", new=io.StringIO()) as stdout, patch("sys.stderr", new=io.StringIO()) as stderr:
            rc = module.main()
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "feedback issue response was not valid JSON")
        self.assertTrue(audits)
        self.assertIn("feedback issue response was not valid JSON", stderr.getvalue())

    def test_submit_feedback_create_system_exit_returns_structured_failure(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_create_system_exit_under_test")

        audits = []
        module.audit_event = lambda *args, **kwargs: audits.append((args, kwargs))
        module.gh_read_json = lambda *args, **kwargs: {"items": []}

        def failing_gh_write_cmd(*args, **kwargs):
            raise SystemExit("gh missing at /Users/snow/private/bin/gh token=ghp_secretvalue user=snow@example.com")

        module.gh_write_cmd = failing_gh_write_cmd

        with patched_argv(
            [
                "submit_feedback.py",
                "--category",
                "tooling-bug",
                "--title",
                "create system exit",
                "--summary",
                "summary",
                "--expected",
                "expected",
                "--actual",
                "actual",
            ]
        ), patch("sys.stdout", new=io.StringIO()) as stdout, patch("sys.stderr", new=io.StringIO()) as stderr:
            rc = module.main()
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["status"], "failed")
        self.assertIsNone(payload["issue_number"])
        self.assertIsNone(payload["issue_url"])
        self.assertIn("gh missing", payload["error"])
        self.assertNotIn("/Users/snow/private", payload["error"])
        self.assertNotIn("ghp_secretvalue", payload["error"])
        self.assertNotIn("snow@example.com", payload["error"])
        self.assertTrue(audits)
        self.assertIn("gh missing", stderr.getvalue())

    def test_submit_feedback_rejects_success_response_missing_required_fields(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_missing_fields_under_test")

        audits = []
        module.audit_event = lambda *args, **kwargs: audits.append((args, kwargs))
        module.gh_read_json = lambda *args, **kwargs: {"items": []}
        module.gh_write_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            json.dumps({"id": 321}),
            "",
        )

        with patched_argv(
            [
                "submit_feedback.py",
                "--category",
                "tooling-bug",
                "--title",
                "bad response",
                "--summary",
                "summary",
                "--expected",
                "expected",
                "--actual",
                "actual",
            ]
        ), patch("sys.stdout", new=io.StringIO()) as stdout, patch("sys.stderr", new=io.StringIO()) as stderr:
            rc = module.main()
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["status"], "failed")
        self.assertIsNone(payload["issue_number"])
        self.assertIsNone(payload["issue_url"])
        self.assertEqual(payload["error"], "feedback issue response missing valid number, html_url")
        self.assertTrue(audits)
        self.assertIn("feedback issue response missing valid number, html_url", stderr.getvalue())

    def test_submit_feedback_audits_lookup_failure_with_structured_output(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_lookup_failure_under_test")

        audits = []
        module.audit_event = lambda *args, **kwargs: audits.append((args, kwargs))

        def failing_gh_read_json(*args, **kwargs):
            raise subprocess.CalledProcessError(1, args[0], "", "gh auth failed")

        module.gh_read_json = failing_gh_read_json
        module.gh_write_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "{}", "")

        with patched_argv(
            [
                "submit_feedback.py",
                "--category",
                "tooling-bug",
                "--title",
                "dedupe lookup failure",
                "--summary",
                "summary",
                "--expected",
                "expected",
                "--actual",
                "actual",
            ]
        ), patch("sys.stdout", new=io.StringIO()) as stdout, patch("sys.stderr", new=io.StringIO()) as stderr:
            rc = module.main()
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["status"], "failed")
        self.assertIsNone(payload["issue_number"])
        self.assertIsNone(payload["issue_url"])
        self.assertIn("dedupe lookup failed", payload["error"])
        self.assertIn("gh auth failed", payload["error"])
        self.assertTrue(audits)
        self.assertIn("dedupe lookup failed", stderr.getvalue())

    def test_submit_feedback_sanitize_text_only_redacts_absolute_paths(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_sanitize_text_under_test")

        sanitized = module.sanitize_text(
            "Repo octo/example uses tmp/file.json and https://example.com/docs/a "
            "plus /Users/snow/workspace/gh-address-cr/scripts/cli.py "
            "and C:\\Users\\snow\\workspace\\notes.txt."
        )

        self.assertIn("octo/example", sanitized)
        self.assertIn("tmp/file.json", sanitized)
        self.assertIn("https://example.com/docs/a", sanitized)
        self.assertIn(".../gh-address-cr/scripts/cli.py", sanitized)
        self.assertIn(".../workspace/notes.txt", sanitized)
        self.assertNotIn("/Users/snow/workspace", sanitized)
        self.assertNotIn("C:\\Users\\snow\\workspace\\notes.txt", sanitized)

    def test_submit_feedback_sanitize_text_redacts_mounted_home_paths(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_sanitize_text_mounted_path_under_test")

        sanitized = module.sanitize_text(
            "Mounted path file is /mnt/c/Users/snow/workspace/gh-address-cr/scripts/cli.py "
            "and build cache is /mnt/c/var/home/snow/tmp/state.json."
        )

        self.assertIn(".../gh-address-cr/scripts/cli.py", sanitized)
        self.assertIn(".../tmp/state.json", sanitized)
        self.assertNotIn("/mnt/c/Users/snow", sanitized)
        self.assertNotIn("/mnt/c/var/home/snow", sanitized)

    def test_submit_feedback_sanitize_text_redacts_file_uri_paths(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_sanitize_text_file_uri_under_test")

        sanitized = module.sanitize_text(
            "Local file URI file:///Users/snow/workspace/gh-address-cr/scripts/cli.py "
            "should be redacted while https://example.com/file:///docs stays intact."
        )

        self.assertIn("file://.../gh-address-cr/scripts/cli.py", sanitized)
        self.assertIn("https://example.com/file:///docs", sanitized)
        self.assertNotIn("file:///Users/snow/workspace", sanitized)

    def test_submit_feedback_sanitize_text_redacts_common_token_assignment_variants(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_sanitize_text_token_variants_under_test")

        sanitized = module.sanitize_text(
            "access_token=supersecret auth-token=hunter2 refresh_token=abc123 "
            "session token=value should all be redacted."
        )

        self.assertIn("access_token=[redacted-token]", sanitized)
        self.assertIn("auth-token=[redacted-token]", sanitized)
        self.assertIn("refresh_token=[redacted-token]", sanitized)
        self.assertIn("token=[redacted-token]", sanitized)
        self.assertNotIn("access_token=supersecret", sanitized)
        self.assertNotIn("auth-token=hunter2", sanitized)
        self.assertNotIn("refresh_token=abc123", sanitized)
        self.assertNotIn("token=value", sanitized)

    def test_submit_feedback_sanitize_command_redacts_key_value_tokens_and_file_uri_args(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_sanitize_command_under_test")

        sanitized = module.sanitize_command(
            "python3 tool.py token=supersecret password=hunter2 "
            "file:///Users/snow/private/state.json https://example.com/file:///docs"
        )

        self.assertIn("token=[redacted-token]", sanitized)
        self.assertIn("password=[redacted-token]", sanitized)
        self.assertIn("file://.../private/state.json", sanitized)
        self.assertIn("https://example.com/file:///docs", sanitized)
        self.assertNotIn("token=supersecret", sanitized)
        self.assertNotIn("password=hunter2", sanitized)
        self.assertNotIn("file:///Users/snow/private/state.json", sanitized)

    def test_submit_feedback_write_failure_sanitizes_error_and_audit_details(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_write_failure_under_test")

        audits = []
        module.audit_event = lambda *args, **kwargs: audits.append((args, kwargs))
        module.gh_read_json = lambda *args, **kwargs: {"items": []}
        module.gh_write_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            "",
            "token=ghp_abcdefghijklmnopqrstuvwxyz12 path=/Users/snow/private/state.json email=alice@example.com",
        )

        with patched_argv(
            [
                "submit_feedback.py",
                "--category",
                "tooling-bug",
                "--title",
                "bad response",
                "--summary",
                "summary",
                "--expected",
                "expected",
                "--actual",
                "actual",
            ]
        ), patch("sys.stdout", new=io.StringIO()) as stdout, patch("sys.stderr", new=io.StringIO()):
            rc = module.main()
            payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("[redacted-token]", payload["error"])
        self.assertIn("email=[redacted]", payload["error"])
        self.assertIn(".../private/state.json", payload["error"])
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz12", payload["error"])
        self.assertNotIn("alice@example.com", payload["error"])
        self.assertNotIn("/Users/snow/private", payload["error"])
        self.assertTrue(audits)
        audit_args, _audit_kwargs = audits[-1]
        self.assertIn("[redacted-token]", audit_args[6]["error"])
        self.assertIn("email=[redacted]", audit_args[6]["error"])
        self.assertIn(".../private/state.json", audit_args[6]["error"])
