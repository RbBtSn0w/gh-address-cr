import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeGitHubClient:
    def __init__(self, *, threads=None, pending_reviews=None, login="agent-login"):
        self.threads = threads or []
        self.pending_reviews = pending_reviews or []
        self.login = login

    def list_threads(self, repo, pr_number):
        return list(self.threads)

    def viewer_login(self):
        return self.login

    def list_pending_reviews(self, repo, pr_number, login=None):
        if not login:
            return list(self.pending_reviews)
        return [
            review
            for review in self.pending_reviews
            if (review.get("user") or {}).get("login") == login or review.get("author_login") == login
        ]


class NativeGateTests(unittest.TestCase):
    def write_session(self, repo: str, pr_number: str, items: dict):
        from gh_address_cr.core.session import SessionManager

        manager = SessionManager(repo, pr_number)
        session = manager.create(status="WAITING_FOR_GATE")
        session["items"] = items
        manager.save(session)
        return manager

    def test_gatekeeper_passes_with_resolved_thread_reply_and_validation_evidence(self):
        from gh_address_cr.core.gate import Gatekeeper

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(
                    repo,
                    pr_number,
                    {
                        "github-thread:THREAD_1": {
                            "item_id": "github-thread:THREAD_1",
                            "item_kind": "github_thread",
                            "thread_id": "THREAD_1",
                            "state": "closed",
                            "reply_evidence": {
                                "reply_url": "https://github.test/reply",
                                "author_login": "agent-login",
                            },
                        },
                        "local-finding:FIXED": {
                            "item_id": "local-finding:FIXED",
                            "item_kind": "local_finding",
                            "state": "fixed",
                            "blocking": False,
                            "validation_evidence": [{"command": "python3 -m unittest tests.test_native_gate"}],
                        },
                    },
                )

                result = Gatekeeper(
                    github_client=FakeGitHubClient(
                        threads=[{"id": "THREAD_1", "isResolved": True}],
                    )
                ).run(repo, pr_number)

                self.assertTrue(result.passed)
                self.assertEqual(result.counts["unresolved_remote_threads_count"], 0)

    def test_gatekeeper_fails_resolved_thread_without_reply_evidence(self):
        from gh_address_cr.core.gate import FINAL_GATE_MISSING_REPLY_EVIDENCE, Gatekeeper

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(
                    repo,
                    pr_number,
                    {
                        "github-thread:THREAD_1": {
                            "item_id": "github-thread:THREAD_1",
                            "item_kind": "github_thread",
                            "thread_id": "THREAD_1",
                            "state": "closed",
                        }
                    },
                )

                result = Gatekeeper(
                    github_client=FakeGitHubClient(
                        threads=[{"id": "THREAD_1", "isResolved": True}],
                    )
                ).run(repo, pr_number)

                self.assertFalse(result.passed)
                self.assertEqual(result.reason_code, FINAL_GATE_MISSING_REPLY_EVIDENCE)

    def test_cli_final_gate_uses_native_gate_without_legacy_script(self):
        from gh_address_cr import cli
        from gh_address_cr.core.session import SessionManager

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            gh.write_text(
                """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:2] == ['api', 'user']:
    print(json.dumps({'login': 'agent-login'}))
elif args[:2] == ['api', 'repos/owner/repo/pulls/123/reviews?per_page=100&page=1']:
    print('[]')
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
                encoding="utf-8",
            )
            gh.chmod(0o755)
            snapshot = Path(tmp) / "threads.jsonl"
            snapshot.write_text(json.dumps({"id": "THREAD_1", "isResolved": True}) + "\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "GH_ADDRESS_CR_STATE_DIR": str(state_dir),
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                },
                clear=False,
            ):
                manager = SessionManager(repo, pr_number)
                session = manager.create(status="WAITING_FOR_GATE")
                session["items"] = {
                    "github-thread:THREAD_1": {
                        "item_id": "github-thread:THREAD_1",
                        "item_kind": "github_thread",
                        "thread_id": "THREAD_1",
                        "state": "closed",
                        "reply_evidence": {
                            "reply_url": "https://github.test/reply",
                            "author_login": "agent-login",
                        },
                    }
                }
                manager.save(session)
                stdout = io.StringIO()
                stderr = io.StringIO()

                with (
                    patch.object(cli, "run_script", side_effect=AssertionError("legacy script")),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    rc = cli.main(["final-gate", "--no-auto-clean", "--snapshot", str(snapshot), repo, pr_number])

                self.assertEqual(rc, 0, stderr.getvalue())
                self.assertIn("Verified: 0 Unresolved Threads found", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
