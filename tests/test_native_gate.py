import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeGitHubClient:
    def __init__(self, *, threads=None, pending_reviews=None, checks=None, login="agent-login"):
        self.threads = threads or []
        self.pending_reviews = pending_reviews or []
        self.checks = checks or []
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

    def list_pr_checks(self, repo, pr_number, *, required=False):
        return [check for check in self.checks if not required or check.get("required")]


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

    def test_gatekeeper_require_checks_fails_non_green_pr_checks(self):
        from gh_address_cr.core.gate import FINAL_GATE_PR_CHECKS_NOT_GREEN, Gatekeeper

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, {})

                result = Gatekeeper(
                    github_client=FakeGitHubClient(
                        checks=[
                            {"name": "unit", "bucket": "pass"},
                            {"name": "integration", "bucket": "pending"},
                        ],
                    )
                ).run(repo, pr_number, require_checks=True)

                self.assertFalse(result.passed)
                self.assertEqual(result.reason_code, FINAL_GATE_PR_CHECKS_NOT_GREEN)
                self.assertEqual(result.counts["pr_checks_count"], 2)
                self.assertEqual(result.counts["pr_checks_pending_count"], 1)

    def test_gatekeeper_require_checks_treats_missing_check_state_as_unknown(self):
        from gh_address_cr.core.gate import FINAL_GATE_PR_CHECKS_NOT_GREEN, Gatekeeper

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, {})

                result = Gatekeeper(github_client=FakeGitHubClient(checks=[{"name": "unit"}])).run(
                    repo, pr_number, require_checks=True
                )

                self.assertFalse(result.passed)
                self.assertEqual(result.reason_code, FINAL_GATE_PR_CHECKS_NOT_GREEN)
                self.assertEqual(result.counts["pr_checks_failed_count"], 1)

    def test_gatekeeper_required_checks_filters_optional_checks(self):
        from gh_address_cr.core.gate import Gatekeeper

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, {})

                result = Gatekeeper(
                    github_client=FakeGitHubClient(
                        checks=[
                            {"name": "required-unit", "bucket": "pass", "required": True},
                            {"name": "optional-flaky", "bucket": "fail", "required": False},
                        ],
                    )
                ).run(repo, pr_number, require_required_checks=True)

                self.assertTrue(result.passed)
                self.assertEqual(result.counts["pr_checks_count"], 1)
                self.assertEqual(result.check_requirement, "required")

    def test_remote_stale_thread_refreshes_as_claimable_blocking_item(self):
        from gh_address_cr.core import gate

        session = {
            "repo": "owner/repo",
            "pr_number": "123",
            "items": {},
        }

        merged = gate.session_with_remote_threads(
            session,
            [
                {
                    "id": "THREAD_STALE",
                    "isResolved": False,
                    "isOutdated": True,
                    "path": "src/stale.py",
                    "line": 12,
                }
            ],
        )

        item = merged["items"]["github-thread:THREAD_STALE"]
        self.assertEqual(item["state"], "stale")
        self.assertEqual(item["status"], "STALE")
        self.assertTrue(item["blocking"])

    def test_remote_thread_refresh_uses_first_comment_for_severity(self):
        from gh_address_cr.core import gate

        session = {
            "repo": "owner/repo",
            "pr_number": "123",
            "items": {},
        }

        merged = gate.session_with_remote_threads(
            session,
            [
                {
                    "id": "THREAD_P1",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/severity.py",
                    "line": 12,
                    "body": "Maintainer reply says Severity: P3",
                    "url": "https://example.test/thread/p1#latest",
                    "first_body": "[P1] Reject unsafe fallback.",
                    "first_url": "https://example.test/thread/p1",
                    "latest_body": "Severity: P3",
                    "latest_url": "https://example.test/thread/p1#latest",
                }
            ],
        )

        item = merged["items"]["github-thread:THREAD_P1"]
        self.assertEqual(item["severity"], "P1")
        self.assertEqual(item["severity_evidence"]["source"], "github_first_comment")
        self.assertEqual(item["severity_evidence"]["observed_from"], "https://example.test/thread/p1")

    def test_remote_thread_refresh_drops_legacy_unbacked_severity(self):
        from gh_address_cr.core import gate

        session = {
            "repo": "owner/repo",
            "pr_number": "123",
            "items": {
                "github-thread:THREAD_LEGACY": {
                    "item_id": "github-thread:THREAD_LEGACY",
                    "item_kind": "github_thread",
                    "source": "github",
                    "thread_id": "THREAD_LEGACY",
                    "severity": "P2",
                    "state": "open",
                    "status": "OPEN",
                }
            },
        }

        merged = gate.session_with_remote_threads(
            session,
            [
                {
                    "id": "THREAD_LEGACY",
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/severity.py",
                    "line": 12,
                    "body": "No explicit severity marker.",
                    "url": "https://example.test/thread/legacy",
                }
            ],
        )

        item = merged["items"]["github-thread:THREAD_LEGACY"]
        self.assertNotIn("severity", item)
        self.assertNotIn("severity_evidence", item)

    def test_stale_thread_without_remote_resolution_does_not_require_reply_evidence(self):
        from gh_address_cr.core import gate

        session = {
            "repo": "owner/repo",
            "pr_number": "123",
            "items": {
                "github-thread:THREAD_STALE": {
                    "item_id": "github-thread:THREAD_STALE",
                    "item_kind": "github_thread",
                    "thread_id": "THREAD_STALE",
                    "state": "stale",
                    "status": "STALE",
                    "blocking": True,
                    "is_outdated": True,
                }
            },
        }

        result = gate.evaluate_final_gate(session)

        self.assertEqual(result.counts["github_threads_missing_reply_count"], 0)
        self.assertEqual(result.counts["blocking_items_count"], 1)
        self.assertEqual(result.counts["blocking_github_items_count"], 1)
        self.assertEqual(result.reason_code, gate.FINAL_GATE_BLOCKING_GITHUB_ITEMS)

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

                self.assertFalse(hasattr(cli, "run_script"))
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    rc = cli.main(["final-gate", "--no-auto-clean", "--snapshot", str(snapshot), repo, pr_number])

                self.assertEqual(rc, 0, stderr.getvalue())
                self.assertIn("Verified: 0 Unresolved Threads found", stdout.getvalue())

    def test_cli_final_gate_require_checks_reports_non_green_checks(self):
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
elif args[:2] == ['pr', 'checks']:
    print(json.dumps([{'name': 'unit', 'bucket': 'fail', 'state': 'failure'}]))
    raise SystemExit(1)
else:
    raise SystemExit(f'unhandled gh args: {args}')
""",
                encoding="utf-8",
            )
            gh.chmod(0o755)
            snapshot = Path(tmp) / "threads.jsonl"
            snapshot.write_text("", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "GH_ADDRESS_CR_STATE_DIR": str(state_dir),
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                },
                clear=False,
            ):
                SessionManager(repo, pr_number).create(status="WAITING_FOR_GATE")
                stdout = io.StringIO()
                stderr = io.StringIO()

                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    rc = cli.main(
                        ["final-gate", "--no-auto-clean", "--require-checks", "--snapshot", str(snapshot), repo, pr_number]
                    )

                self.assertEqual(rc, 5)
                self.assertIn("pr_checks_failed_count=1", stdout.getvalue())
                self.assertIn("non-green PR check", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
