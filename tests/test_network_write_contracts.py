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
        module.gh_read_json = lambda *args, **kwargs: []
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
