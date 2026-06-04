import importlib.util
import io
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tests.helpers import PythonScriptTestCase, IMPLEMENTATIONS_DIR


@contextmanager
def patched_argv(argv: list[str]):
    with patch.object(sys, "argv", argv):
        yield


class NetworkWriteContractTest(PythonScriptTestCase):
    def load_module(self, script_name: str, module_name: str):
        path = IMPLEMENTATIONS_DIR / script_name
        sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        try:
            with patch.dict("os.environ", {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)}, clear=False):
                spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def test_submit_feedback_audits_invalid_json_response(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_under_test")

        audits = []
        module.audit_event = lambda *args, **kwargs: audits.append((args, kwargs))
        module.gh_read_json = lambda *args, **kwargs: {"items": []}
        module.gh_write_cmd = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "not-json", "")

        with (
            patched_argv(
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
            ),
            patch("sys.stdout", new=io.StringIO()) as stdout,
            patch("sys.stderr", new=io.StringIO()) as stderr,
        ):
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

        with (
            patched_argv(
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
            ),
            patch("sys.stdout", new=io.StringIO()) as stdout,
            patch("sys.stderr", new=io.StringIO()) as stderr,
        ):
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

        with (
            patched_argv(
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
            ),
            patch("sys.stdout", new=io.StringIO()) as stdout,
            patch("sys.stderr", new=io.StringIO()) as stderr,
        ):
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

        with (
            patched_argv(
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
            ),
            patch("sys.stdout", new=io.StringIO()) as stdout,
            patch("sys.stderr", new=io.StringIO()) as stderr,
        ):
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
            "plus /Users/snow/workspace/skill/scripts/cli.py "
            "and C:\\Users\\snow\\workspace\\notes.txt."
        )

        self.assertIn("octo/example", sanitized)
        self.assertIn("tmp/file.json", sanitized)
        self.assertIn("https://example.com/docs/a", sanitized)
        self.assertIn(".../skill/scripts/cli.py", sanitized)
        self.assertIn(".../workspace/notes.txt", sanitized)
        self.assertNotIn("/Users/snow/workspace", sanitized)
        self.assertNotIn("C:\\Users\\snow\\workspace\\notes.txt", sanitized)

    def test_submit_feedback_sanitize_text_redacts_mounted_home_paths(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_sanitize_text_mounted_path_under_test")

        sanitized = module.sanitize_text(
            "Mounted path file is /mnt/c/Users/snow/workspace/skill/scripts/cli.py "
            "and build cache is /mnt/c/var/home/snow/tmp/state.json."
        )

        self.assertIn(".../skill/scripts/cli.py", sanitized)
        self.assertIn(".../tmp/state.json", sanitized)
        self.assertNotIn("/mnt/c/Users/snow", sanitized)
        self.assertNotIn("/mnt/c/var/home/snow", sanitized)

    def test_submit_feedback_sanitize_text_redacts_file_uri_paths(self):
        module = self.load_module("submit_feedback.py", "submit_feedback_sanitize_text_file_uri_under_test")

        sanitized = module.sanitize_text(
            "Local file URI file:///Users/snow/workspace/skill/scripts/cli.py "
            "should be redacted while https://example.com/file:///docs stays intact."
        )

        self.assertIn("file://.../skill/scripts/cli.py", sanitized)
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

        with (
            patched_argv(
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
            ),
            patch("sys.stdout", new=io.StringIO()) as stdout,
            patch("sys.stderr", new=io.StringIO()),
        ):
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
