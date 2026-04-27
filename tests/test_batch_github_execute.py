import importlib.util
import io
import json
import subprocess
import sys
from contextlib import contextmanager
from unittest.mock import patch

from tests.helpers import PythonScriptTestCase, CR_LOOP_PY


BATCH_GITHUB_EXECUTE_PY = CR_LOOP_PY.parent / "batch_github_execute.py"


@contextmanager
def patched_argv(argv: list[str]):
    with patch.object(sys, "argv", argv):
        yield


@contextmanager
def patched_stdin(text: str):
    with patch.object(sys, "stdin", io.StringIO(text)):
        yield


class BatchGitHubExecuteTestCase(PythonScriptTestCase):
    def load_module(self):
        sys.path.insert(0, str(BATCH_GITHUB_EXECUTE_PY.parent))
        spec = importlib.util.spec_from_file_location("batch_github_execute_under_test", BATCH_GITHUB_EXECUTE_PY)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def test_batch_github_execute_submits_current_pending_reviews(self):
        module = self.load_module()
        action_payload = json.dumps(
            [
                {
                    "item_id": "github-thread:THREAD_1",
                    "thread_id": "THREAD_1",
                    "reply_body": "Reply body",
                    "resolve": True,
                }
            ]
        )
        submitted = []

        def fake_list_pending_review_ids(repo, pr_number, login):
            return {11, 22}

        def fake_submit_pending_reviews_result(repo, pr_number, review_ids):
            submitted.extend(review_ids)
            return {"status": "succeeded", "submitted": list(review_ids), "error": None}

        def fake_write_cmd(cmd, *, input_text=None, check=False):
            self.assertIn("gh", cmd[0])
            self.assertIn("graphql", cmd)
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    {
                        "data": {
                            "reply0": {"comment": {"url": "https://example.test/reply"}},
                            "resolve0": {"thread": {"id": "THREAD_1", "isResolved": True}},
                        }
                    }
                ),
                "",
            )

        module.list_pending_review_ids = fake_list_pending_review_ids
        module.submit_pending_reviews_result = fake_submit_pending_reviews_result
        module.github_viewer_login = lambda: "tester"
        module.gh_write_cmd = fake_write_cmd
        module.audit_event = lambda *args, **kwargs: None

        with (
            patched_argv(
                [
                    "batch_github_execute.py",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                ]
            ),
            patched_stdin(action_payload),
        ):
            with patch("sys.stdout", new=io.StringIO()) as stdout:
                rc = module.main()
                payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(submitted, [11, 22])
        self.assertEqual(payload["github-thread:THREAD_1"]["status"], "succeeded")
        self.assertEqual(payload["github-thread:THREAD_1"]["reply_url"], "https://example.test/reply")

    def test_batch_github_execute_returns_nonzero_when_graphql_fails(self):
        module = self.load_module()
        action_payload = json.dumps(
            [
                {
                    "item_id": "github-thread:THREAD_2",
                    "thread_id": "THREAD_2",
                    "reply_body": "Reply body",
                    "resolve": True,
                }
            ]
        )
        submitted = []

        def fake_list_pending_review_ids(repo, pr_number, login):
            return set()

        def fake_submit_pending_reviews_result(repo, pr_number, review_ids):
            submitted.extend(review_ids)
            return {"status": "succeeded", "submitted": list(review_ids), "error": None}

        def fake_write_cmd(cmd, *, input_text=None, check=False):
            return subprocess.CompletedProcess(cmd, 1, "", "graphql failed")

        module.list_pending_review_ids = fake_list_pending_review_ids
        module.submit_pending_reviews_result = fake_submit_pending_reviews_result
        module.github_viewer_login = lambda: "tester"
        module.gh_write_cmd = fake_write_cmd
        module.is_transient_gh_failure = lambda *_args, **_kwargs: True
        module.audit_event = lambda *args, **kwargs: None

        with (
            patched_argv(
                [
                    "batch_github_execute.py",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                ]
            ),
            patched_stdin(action_payload),
        ):
            with patch("sys.stdout", new=io.StringIO()) as stdout:
                rc = module.main()
                payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(submitted, [])
        self.assertEqual(payload["github-thread:THREAD_2"]["status"], "retryable")
        self.assertEqual(payload["github-thread:THREAD_2"]["error"], "graphql failed")

    def test_batch_github_execute_marks_action_failed_when_thread_id_is_missing(self):
        module = self.load_module()
        action_payload = json.dumps(
            [
                {
                    "item_id": "github-thread:MISSING_THREAD_ID",
                    "reply_body": "Reply body",
                    "resolve": True,
                }
            ]
        )
        submitted = []
        audit_calls = []

        module.list_pending_review_ids = lambda *_args, **_kwargs: set()
        module.submit_pending_reviews_result = lambda *_args, **_kwargs: {
            "status": "skipped",
            "submitted": submitted,
            "error": None,
        }
        module.github_viewer_login = lambda: "tester"
        module.gh_write_cmd = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("gh_write_cmd should not be called")
        )
        module.audit_event = lambda *args, **kwargs: audit_calls.append((args, kwargs))

        with (
            patched_argv(
                [
                    "batch_github_execute.py",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                ]
            ),
            patched_stdin(action_payload),
        ):
            with patch("sys.stdout", new=io.StringIO()) as stdout:
                rc = module.main()
                payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["github-thread:MISSING_THREAD_ID"]["status"], "failed")
        self.assertIn("thread_id", payload["github-thread:MISSING_THREAD_ID"]["error"])
        self.assertTrue(audit_calls)

    def test_batch_github_execute_rejects_resolve_only_without_reply_evidence(self):
        module = self.load_module()
        workspace = self.workspace_dir()
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repo": self.repo,
                    "pr_number": self.pr,
                    "items": {
                        "github-thread:THREAD_REPLY_REQUIRED": {
                            "item_id": "github-thread:THREAD_REPLY_REQUIRED",
                            "item_kind": "github_thread",
                            "origin_ref": "THREAD_REPLY_REQUIRED",
                            "status": "OPEN",
                            "reply_posted": False,
                            "reply_url": None,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        action_payload = json.dumps(
            [
                {
                    "item_id": "github-thread:THREAD_REPLY_REQUIRED",
                    "thread_id": "THREAD_REPLY_REQUIRED",
                    "resolve": True,
                }
            ]
        )

        module.list_pending_review_ids = lambda *_args, **_kwargs: set()
        module.submit_pending_reviews_result = lambda *_args, **_kwargs: {
            "status": "skipped",
            "submitted": [],
            "error": None,
        }
        module.github_viewer_login = lambda: "tester"
        module.audit_event = lambda *args, **kwargs: None
        module.gh_write_cmd = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("gh_write_cmd should not be called")
        )

        with (
            patched_argv(
                [
                    "batch_github_execute.py",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                ]
            ),
            patched_stdin(action_payload),
        ):
            with patch("sys.stdout", new=io.StringIO()) as stdout:
                rc = module.main()
                payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["github-thread:THREAD_REPLY_REQUIRED"]["status"], "failed")
        self.assertIn("reply evidence", payload["github-thread:THREAD_REPLY_REQUIRED"]["error"])

    def test_batch_github_execute_runs_reply_before_resolve_for_combined_actions(self):
        module = self.load_module()
        action_payload = json.dumps(
            [
                {
                    "item_id": "github-thread:THREAD_PHASED",
                    "thread_id": "THREAD_PHASED",
                    "reply_body": "Reply body",
                    "resolve": True,
                }
            ]
        )
        calls = []

        def fake_write_cmd(cmd, *, input_text=None, check=False):
            query = next(part.split("=", 1)[1] for part in cmd if part.startswith("query="))
            calls.append(query)
            if len(calls) == 1:
                self.assertIn("addPullRequestReviewThreadReply", query)
                self.assertNotIn("resolveReviewThread", query)
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps({"data": {"reply0": {"comment": {"url": "https://example.test/reply"}}}}),
                    "",
                )
            if len(calls) == 2:
                self.assertIn("resolveReviewThread", query)
                self.assertNotIn("addPullRequestReviewThreadReply", query)
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps({"data": {"resolve0": {"thread": {"id": "THREAD_PHASED", "isResolved": True}}}}),
                    "",
                )
            raise AssertionError(f"unexpected extra GraphQL call: {cmd}")

        module.list_pending_review_ids = lambda *_args, **_kwargs: set()
        module.submit_pending_reviews_result = lambda *_args, **_kwargs: {
            "status": "skipped",
            "submitted": [],
            "error": None,
        }
        module.github_viewer_login = lambda: "tester"
        module.audit_event = lambda *args, **kwargs: None
        module.gh_write_cmd = fake_write_cmd

        with (
            patched_argv(
                [
                    "batch_github_execute.py",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                ]
            ),
            patched_stdin(action_payload),
        ):
            with patch("sys.stdout", new=io.StringIO()) as stdout:
                rc = module.main()
                payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(payload["github-thread:THREAD_PHASED"]["status"], "succeeded")
        self.assertEqual(payload["github-thread:THREAD_PHASED"]["reply_url"], "https://example.test/reply")
        self.assertTrue(payload["github-thread:THREAD_PHASED"]["resolved"])

    def test_batch_github_execute_does_not_resolve_when_reply_phase_fails(self):
        module = self.load_module()
        action_payload = json.dumps(
            [
                {
                    "item_id": "github-thread:THREAD_REPLY_FAILS",
                    "thread_id": "THREAD_REPLY_FAILS",
                    "reply_body": "Reply body",
                    "resolve": True,
                }
            ]
        )
        calls = []

        def fake_write_cmd(cmd, *, input_text=None, check=False):
            query = next(part.split("=", 1)[1] for part in cmd if part.startswith("query="))
            calls.append(query)
            self.assertIn("addPullRequestReviewThreadReply", query)
            self.assertNotIn("resolveReviewThread", query)
            return subprocess.CompletedProcess(
                cmd,
                1,
                json.dumps({"data": {}, "errors": [{"message": "reply failed", "path": ["reply0"]}]}),
                "reply failed",
            )

        module.list_pending_review_ids = lambda *_args, **_kwargs: set()
        module.submit_pending_reviews_result = lambda *_args, **_kwargs: {
            "status": "skipped",
            "submitted": [],
            "error": None,
        }
        module.github_viewer_login = lambda: "tester"
        module.audit_event = lambda *args, **kwargs: None
        module.gh_write_cmd = fake_write_cmd

        with (
            patched_argv(
                [
                    "batch_github_execute.py",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                ]
            ),
            patched_stdin(action_payload),
        ):
            with patch("sys.stdout", new=io.StringIO()) as stdout:
                rc = module.main()
                payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(payload["github-thread:THREAD_REPLY_FAILS"]["status"], "failed")
        self.assertEqual(payload["github-thread:THREAD_REPLY_FAILS"]["error"], "reply failed")
        self.assertIsNone(payload["github-thread:THREAD_REPLY_FAILS"]["resolved"])

    def test_batch_github_execute_marks_successful_actions_unknown_when_submit_is_partial(self):
        module = self.load_module()
        action_payload = json.dumps(
            [
                {
                    "item_id": "github-thread:THREAD_3",
                    "thread_id": "THREAD_3",
                    "reply_body": "Reply body",
                    "resolve": True,
                }
            ]
        )

        module.list_pending_review_ids = lambda *_args, **_kwargs: {11}
        module.submit_pending_reviews_result = lambda *_args, **_kwargs: {
            "status": "unknown",
            "submitted": [],
            "error": "submit pending reviews failed",
        }
        module.github_viewer_login = lambda: "tester"
        module.gh_write_cmd = lambda cmd, *, input_text=None, check=False: subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps(
                {
                    "data": {
                        "reply0": {"comment": {"url": "https://example.test/reply"}},
                        "resolve0": {"thread": {"id": "THREAD_3", "isResolved": True}},
                    }
                }
            ),
            "",
        )
        module.audit_event = lambda *args, **kwargs: None

        with (
            patched_argv(
                [
                    "batch_github_execute.py",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                ]
            ),
            patched_stdin(action_payload),
        ):
            with patch("sys.stdout", new=io.StringIO()) as stdout:
                rc = module.main()
                payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["github-thread:THREAD_3"]["status"], "unknown")
        self.assertEqual(payload["github-thread:THREAD_3"]["reply_url"], "https://example.test/reply")
        self.assertIn("submit pending reviews failed", payload["github-thread:THREAD_3"]["error"])

    def test_batch_github_execute_returns_nonzero_when_item_result_is_incomplete(self):
        module = self.load_module()
        action_payload = json.dumps(
            [
                {
                    "item_id": "github-thread:THREAD_6",
                    "thread_id": "THREAD_6",
                    "reply_body": "Reply body",
                    "resolve": True,
                }
            ]
        )

        module.list_pending_review_ids = lambda *_args, **_kwargs: set()
        module.submit_pending_reviews_result = lambda *_args, **_kwargs: {
            "status": "skipped",
            "submitted": [],
            "error": None,
        }
        module.github_viewer_login = lambda: "tester"
        module.audit_event = lambda *args, **kwargs: None
        module.gh_write_cmd = lambda cmd, *, input_text=None, check=False: subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps({"data": {"reply0": {"comment": {}}}}),
            "",
        )

        with (
            patched_argv(
                [
                    "batch_github_execute.py",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                ]
            ),
            patched_stdin(action_payload),
        ):
            with patch("sys.stdout", new=io.StringIO()) as stdout:
                rc = module.main()
                payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(payload["github-thread:THREAD_6"]["status"], "unknown")

    def test_batch_github_execute_scans_pending_reviews_once(self):
        module = self.load_module()
        action_payload = json.dumps(
            [
                {
                    "item_id": "github-thread:THREAD_4",
                    "thread_id": "THREAD_4",
                    "reply_body": "Reply body",
                    "resolve": True,
                }
            ]
        )
        calls = {"count": 0}

        def fake_list_pending_review_ids(*_args, **_kwargs):
            calls["count"] += 1
            return {11}

        module.list_pending_review_ids = fake_list_pending_review_ids
        module.submit_pending_reviews_result = lambda *_args, **_kwargs: {
            "status": "succeeded",
            "submitted": [11],
            "error": None,
        }
        module.github_viewer_login = lambda: "tester"
        module.gh_write_cmd = lambda cmd, *, input_text=None, check=False: subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps(
                {
                    "data": {
                        "reply0": {"comment": {"url": "https://example.test/reply"}},
                        "resolve0": {"thread": {"id": "THREAD_4", "isResolved": True}},
                    }
                }
            ),
            "",
        )
        module.audit_event = lambda *args, **kwargs: None

        with (
            patched_argv(
                [
                    "batch_github_execute.py",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                ]
            ),
            patched_stdin(action_payload),
        ):
            with patch("sys.stdout", new=io.StringIO()) as stdout:
                rc = module.main()
                payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["github-thread:THREAD_4"]["status"], "succeeded")
        self.assertEqual(calls["count"], 1)

    def test_batch_github_execute_reindexes_executable_actions_after_skips(self):
        module = self.load_module()
        action_payload = json.dumps(
            [
                {
                    "item_id": "github-thread:MISSING_THREAD_ID",
                    "reply_body": "Reply body",
                    "resolve": True,
                },
                {
                    "item_id": "github-thread:THREAD_5",
                    "thread_id": "THREAD_5",
                    "reply_body": "Reply body",
                    "resolve": True,
                },
            ]
        )

        module.list_pending_review_ids = lambda *_args, **_kwargs: set()
        module.submit_pending_reviews_result = lambda *_args, **_kwargs: {
            "status": "skipped",
            "submitted": [],
            "error": None,
        }
        module.github_viewer_login = lambda: "tester"
        module.audit_event = lambda *args, **kwargs: None
        queries = []

        def fake_write_cmd(cmd, *, input_text=None, check=False):
            query_arg = next(part for part in cmd if part.startswith("query="))
            queries.append(query_arg)
            self.assertIn("0", query_arg)
            self.assertNotIn("reply1", query_arg)
            self.assertNotIn("resolve1", query_arg)
            if len(queries) == 1:
                self.assertIn("reply0", query_arg)
                self.assertNotIn("resolve0", query_arg)
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps({"data": {"reply0": {"comment": {"url": "https://example.test/reply"}}}}),
                    "",
                )
            if len(queries) == 2:
                self.assertIn("resolve0", query_arg)
                self.assertNotIn("reply0", query_arg)
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps({"data": {"resolve0": {"thread": {"id": "THREAD_5", "isResolved": True}}}}),
                    "",
                )
            raise AssertionError(f"unexpected extra GraphQL call: {cmd}")

        module.gh_write_cmd = fake_write_cmd

        with (
            patched_argv(
                [
                    "batch_github_execute.py",
                    "--repo",
                    self.repo,
                    "--pr",
                    self.pr,
                ]
            ),
            patched_stdin(action_payload),
        ):
            with patch("sys.stdout", new=io.StringIO()) as stdout:
                rc = module.main()
                payload = json.loads(stdout.getvalue())

        self.assertNotEqual(rc, 0)
        self.assertEqual(len(queries), 2)
        self.assertEqual(payload["github-thread:MISSING_THREAD_ID"]["status"], "failed")
        self.assertEqual(payload["github-thread:THREAD_5"]["status"], "succeeded")
