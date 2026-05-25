import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


def open_item(item_id="local:1"):
    return {
        "item_id": item_id,
        "item_kind": "local_finding",
        "source": "json",
        "title": "Needs classification",
        "body": "Classify before fixer lease.",
        "path": "src/example.py",
        "line": 1,
        "state": "open",
        "status": "OPEN",
        "blocking": True,
        "allowed_actions": ["fix", "clarify", "defer", "reject"],
    }


class NativeWorkflowTests(unittest.TestCase):
    def write_session(self, repo: str, pr_number: str, item: dict):
        from gh_address_cr.core.session import SessionManager

        manager = SessionManager(repo, pr_number)
        session = manager.create(status="WAITING_FOR_CLASSIFICATION")
        session["items"] = {item["item_id"]: item}
        manager.save(session)
        return manager

    def test_record_classification_unblocks_fixer_action_request(self):
        from gh_address_cr.core import workflow

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, open_item())

                classified = workflow.record_classification(
                    repo,
                    pr_number,
                    item_id="local:1",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect.",
                )
                requested = workflow.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")

                session = manager.load()
                evidence_rows = [
                    json.loads(line) for line in Path(session["ledger_path"]).read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(classified["status"], "CLASSIFICATION_RECORDED")
                self.assertEqual(session["items"]["local:1"]["classification_evidence"]["classification"], "fix")
                self.assertEqual(requested["status"], "ACTION_REQUESTED")
                self.assertEqual(evidence_rows[0]["event_type"], "classification_recorded")
                self.assertEqual(evidence_rows[0]["agent_id"], "triage-1")

    def test_record_classification_releases_active_triage_lease_for_fixer(self):
        from gh_address_cr.core import workflow

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, open_item())

                triage = workflow.issue_action_request(repo, pr_number, role="triage", agent_id="triage-1")
                classified = workflow.record_classification(
                    repo,
                    pr_number,
                    item_id="local:1",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect.",
                )
                fixer = workflow.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")

                session = manager.load()
                triage_lease = session["leases"][triage["lease_id"]]
                fixer_lease = session["leases"][fixer["lease_id"]]
                self.assertEqual(classified["status"], "CLASSIFICATION_RECORDED")
                self.assertEqual(classified["released_lease_id"], triage["lease_id"])
                self.assertEqual(triage_lease["status"], "released")
                self.assertEqual(triage_lease["reason"], "classification_recorded")
                self.assertEqual(fixer["status"], "ACTION_REQUESTED")
                self.assertEqual(fixer_lease["role"], "fixer")
                self.assertEqual(session["items"]["local:1"]["active_lease_id"], fixer["lease_id"])

    def test_record_classification_rejects_unknown_item_without_mutation(self):
        from gh_address_cr.core import workflow

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, open_item())

                with self.assertRaises(workflow.WorkflowError) as context:
                    workflow.record_classification(
                        repo,
                        pr_number,
                        item_id="missing",
                        classification="fix",
                        agent_id="triage-1",
                        note="No item.",
                    )

                session = manager.load()
                self.assertEqual(context.exception.reason_code, "ITEM_NOT_FOUND")
                self.assertNotIn("classification_evidence", session["items"]["local:1"])

    def test_record_classification_rejects_unsupported_classification(self):
        from gh_address_cr.core import workflow

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, open_item())

                with self.assertRaises(workflow.WorkflowError) as context:
                    workflow.record_classification(
                        repo,
                        pr_number,
                        item_id="local:1",
                        classification="maybe",
                        agent_id="triage-1",
                        note="Unsupported.",
                    )

                self.assertEqual(context.exception.reason_code, "UNSUPPORTED_CLASSIFICATION")

    def test_publish_github_thread_response_posts_reply_resolves_and_closes_item(self):
        from gh_address_cr.core import workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []
                self.resolved = []

            def viewer_login(self):
                return "agent-login"

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append((repo, pr_number, thread_id, body))
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                self.resolved.append((repo, pr_number, thread_id))
                return True

        repo = "owner/repo"
        pr_number = "123"
        item = {
            "item_id": "github-thread:THREAD_1",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
            "state": "publish_ready",
            "status": "OPEN",
            "blocking": True,
            "accepted_response": {
                "resolution": "clarify",
                "note": "Need maintainer input.",
                "reply_markdown": "Can you confirm the intended behavior?",
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()

                result = workflow.publish_github_thread_responses(repo, pr_number, github_client=client)

                session = manager.load()
                updated = session["items"]["github-thread:THREAD_1"]
                event_types = [
                    json.loads(line)["event_type"]
                    for line in Path(session["ledger_path"]).read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(result["status"], "PUBLISH_COMPLETE")
                self.assertEqual(result["published_count"], 1)
                expected_reply = (
                    "Thanks for the review.\n"
                    "\n"
                    "Analysis & Rationale:\n"
                    "- Can you confirm the intended behavior?\n"
                    "\n"
                    "Decision:\n"
                    "- No code changes were made for this specific comment.\n"
                    "\n"
                    "If you feel this still needs an adjustment, let me know and I can follow up with a patch!\n"
                )
                self.assertEqual(client.replies[0], (repo, pr_number, "THREAD_1", expected_reply))
                self.assertEqual(client.resolved[0], (repo, pr_number, "THREAD_1"))
                self.assertEqual(updated["state"], "closed")
                self.assertEqual(updated["status"], "CLOSED")
                self.assertFalse(updated["blocking"])
                self.assertTrue(updated["handled"])
                self.assertEqual(updated["reply_url"], "https://github.test/reply")
                self.assertEqual(updated["reply_evidence"]["author_login"], "agent-login")
                self.assertIn("reply_posted", event_types)
                self.assertIn("thread_resolved", event_types)
                self.assertIn("response_published", event_types)

    def test_submit_action_response_with_publish_posts_and_resolves_thread(self):
        from gh_address_cr.core import workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []
                self.resolved = []

            def viewer_login(self):
                return "agent-login"

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append((repo, pr_number, thread_id, body))
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                self.resolved.append((repo, pr_number, thread_id))
                return True

        repo = "owner/repo"
        pr_number = "123"
        item = {
            "item_id": "github-thread:THREAD_1",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
            "state": "open",
            "status": "OPEN",
            "blocking": True,
            "classification_evidence": {"classification": "fix", "record_id": "ev_classified"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, item)
                request_info = workflow.issue_action_request(repo, pr_number, role="fixer", agent_id="codex-1")
                request = json.loads(Path(request_info["request_path"]).read_text(encoding="utf-8"))
                response_path = Path(tmp) / "action-response.json"
                response_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "request_id": request["request_id"],
                            "lease_id": request["lease_id"],
                            "agent_id": "codex-1",
                            "resolution": "fix",
                            "note": "Fixed thread issue.",
                            "files": ["src/example.py"],
                            "validation_commands": [
                                {"command": "python3 -m unittest tests.test_example", "result": "passed"}
                            ],
                            "fix_reply": {
                                "summary": "Fixed thread issue.",
                                "commit_hash": "abc123",
                                "files": ["src/example.py"],
                                "why": "The guarded path now covers the review case.",
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                client = FakeGitHubClient()

                result = workflow.submit_action_response(
                    repo,
                    pr_number,
                    response_path=response_path,
                    publish=True,
                    github_client=client,
                )

                session = manager.load()
                self.assertEqual(result["status"], "ACTION_ACCEPTED")
                self.assertEqual(result["publish"]["status"], "PUBLISH_COMPLETE")
                self.assertEqual(client.replies[0][2], "THREAD_1")
                self.assertEqual(client.resolved[0], (repo, pr_number, "THREAD_1"))
                self.assertEqual(session["items"]["github-thread:THREAD_1"]["state"], "closed")
                self.assertEqual(session["items"]["github-thread:THREAD_1"]["reply_evidence"]["author_login"], "agent-login")

    def test_publish_with_no_ready_items_does_not_require_viewer_login(self):
        from gh_address_cr.core import workflow

        class FakeGitHubClient:
            def viewer_login(self):
                raise AssertionError("viewer_login should not be called without publish-ready work")

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, open_item())

                result = workflow.publish_github_thread_responses(repo, pr_number, github_client=FakeGitHubClient())

                self.assertEqual(result["status"], "NO_PUBLISH_READY_ITEMS")

    def test_publish_ready_thread_survives_remote_refresh_before_publish(self):
        from gh_address_cr.core import gate, workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []
                self.resolved = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append((repo, pr_number, thread_id, body))
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                self.resolved.append((repo, pr_number, thread_id))
                return True

        repo = "owner/repo"
        pr_number = "123"
        item = {
            "item_id": "github-thread:THREAD_1",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
            "state": "publish_ready",
            "status": "OPEN",
            "blocking": True,
            "publish_resolution": "fix",
            "accepted_response": {
                "resolution": "fix",
                "note": "Fixed thread issue.",
                "files": ["src/example.py"],
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                "fix_reply": {
                    "summary": "Added the missing input guard.",
                    "commit_hash": "abc123",
                    "files": ["src/example.py"],
                    "why": "The input is now checked before use.",
                },
            },
        }
        remote_threads = [
            {
                "id": "THREAD_1",
                "isResolved": False,
                "isOutdated": False,
                "path": "src/example.py",
                "line": 12,
                "url": "https://github.test/thread",
                "body": "Please validate this input.",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, item)
                refreshed = gate.session_with_remote_threads(manager.load(), remote_threads)
                manager.save(refreshed)
                client = FakeGitHubClient()

                result = workflow.publish_github_thread_responses(repo, pr_number, github_client=client)

                session = manager.load()
                self.assertEqual(result["status"], "PUBLISH_COMPLETE")
                self.assertEqual(client.replies[0][2], "THREAD_1")
                self.assertEqual(client.resolved[0], (repo, pr_number, "THREAD_1"))
                self.assertEqual(session["items"]["github-thread:THREAD_1"]["state"], "closed")

    def test_remote_refresh_recovers_publish_ready_from_accepted_evidence(self):
        from gh_address_cr.core import gate, workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []
                self.resolved = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append((repo, pr_number, thread_id, body))
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                self.resolved.append((repo, pr_number, thread_id))
                return True

        repo = "owner/repo"
        pr_number = "123"
        item = {
            "item_id": "github-thread:THREAD_1",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
            "state": "open",
            "status": "OPEN",
            "blocking": True,
            "publish_resolution": "fix",
            "accepted_response": {
                "resolution": "fix",
                "note": "Fixed thread issue.",
                "files": ["src/example.py"],
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                "fix_reply": {
                    "summary": "Added the missing input guard.",
                    "commit_hash": "abc123",
                    "files": ["src/example.py"],
                    "why": "The input is now checked before use.",
                },
            },
        }
        remote_threads = [
            {
                "id": "THREAD_1",
                "isResolved": False,
                "isOutdated": False,
                "path": "src/example.py",
                "line": 12,
                "url": "https://github.test/thread",
                "body": "Please validate this input.",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, item)
                refreshed = gate.session_with_remote_threads(manager.load(), remote_threads)
                manager.save(refreshed)

                self.assertEqual(refreshed["items"]["github-thread:THREAD_1"]["state"], "publish_ready")

                client = FakeGitHubClient()
                result = workflow.publish_github_thread_responses(repo, pr_number, github_client=client)

                session = manager.load()
                self.assertEqual(result["status"], "PUBLISH_COMPLETE")
                self.assertEqual(client.replies[0][2], "THREAD_1")
                self.assertEqual(client.resolved[0], (repo, pr_number, "THREAD_1"))
                self.assertEqual(session["items"]["github-thread:THREAD_1"]["state"], "closed")

    def test_publish_github_thread_fix_uses_documented_reply_template(self):
        from gh_address_cr.core import workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append(body)
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                return True

        repo = "owner/repo"
        pr_number = "123"
        item = {
            "item_id": "github-thread:THREAD_1",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
            "severity": "P1",
            "state": "publish_ready",
            "status": "OPEN",
            "blocking": True,
            "publish_resolution": "fix",
            "accepted_response": {
                "resolution": "fix",
                "note": "Fixed thread issue.",
                "files": ["src/example.py"],
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                "fix_reply": {
                    "summary": "Added the missing input guard.",
                    "commit_hash": "abc123",
                    "files": ["src/example.py"],
                    "why": "The input is now checked before use.",
                },
            },
        }
        expected = (
            "Fixed in `abc123`.\n"
            "\n"
            "Severity: `P1`\n"
            "\n"
            "What I changed:\n"
            "- `src/example.py`: Added the missing input guard.\n"
            "\n"
            "Why this addresses the CR:\n"
            "- The input is now checked before use.\n"
            "- High-severity path validated with targeted regression checks.\n"
            "\n"
            "Validation:\n"
            "- `python3 -m unittest tests.test_example`\n"
            "- Result: passed\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()

                workflow.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertEqual(client.replies[0], expected)

    def test_publish_github_thread_fix_without_severity_does_not_default_to_p2(self):
        from gh_address_cr.core import workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append(body)
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                return True

        repo = "owner/repo"
        pr_number = "123"
        item = {
            "item_id": "github-thread:THREAD_1",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
            "state": "publish_ready",
            "status": "OPEN",
            "blocking": True,
            "publish_resolution": "fix",
            "accepted_response": {
                "resolution": "fix",
                "note": "Fixed thread issue.",
                "files": ["src/example.py"],
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                "fix_reply": {
                    "summary": "Added the missing input guard.",
                    "commit_hash": "abc123",
                    "files": ["src/example.py"],
                    "why": "The input is now checked before use.",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()

                workflow.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertNotIn("Severity:", client.replies[0])
                self.assertNotIn("Medium-severity path", client.replies[0])

    def test_publish_github_thread_fix_uses_severity_specific_template_lines(self):
        from gh_address_cr.core import workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append(body)
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                return True

        expectations = {
            "P1": "- High-severity path validated with targeted regression checks.",
            "P2": "- Medium-severity path validated and aligned with expected workflow.",
            "P3": "- Low-severity improvement validated for non-breaking behavior.",
        }
        for severity, expected_line in expectations.items():
            with self.subTest(severity=severity):
                repo = "owner/repo"
                pr_number = "123"
                item = {
                    "item_id": "github-thread:THREAD_1",
                    "item_kind": "github_thread",
                    "source": "github",
                    "thread_id": "THREAD_1",
                    "severity": severity,
                    "state": "publish_ready",
                    "status": "OPEN",
                    "blocking": True,
                    "publish_resolution": "fix",
                    "accepted_response": {
                        "resolution": "fix",
                        "note": "Fixed thread issue.",
                        "files": ["src/example.py"],
                        "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                        "fix_reply": {
                            "summary": "Added the missing input guard.",
                            "commit_hash": "abc123",
                            "files": ["src/example.py"],
                            "why": "The input is now checked before use.",
                        },
                    },
                }
                with tempfile.TemporaryDirectory() as tmp:
                    with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                        self.write_session(repo, pr_number, item)
                        client = FakeGitHubClient()

                        workflow.publish_github_thread_responses(repo, pr_number, github_client=client)

                        self.assertIn(f"Severity: `{severity}`", client.replies[0])
                        self.assertIn(expected_line, client.replies[0])

    def test_publish_github_thread_fix_ignores_reply_markdown_when_fix_reply_exists(self):
        from gh_address_cr.core import workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append(body)
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                return True

        repo = "owner/repo"
        pr_number = "123"
        item = {
            "item_id": "github-thread:THREAD_1",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
            "severity": "P2",
            "state": "publish_ready",
            "status": "OPEN",
            "blocking": True,
            "publish_resolution": "fix",
            "accepted_response": {
                "resolution": "fix",
                "note": "Fixed thread issue.",
                "files": ["src/example.py"],
                "reply_markdown": "Legacy handwritten reply must not be used for fix.",
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                "fix_reply": {
                    "commit_hash": "abc123",
                    "files": ["src/example.py"],
                    "why": "The input is now checked before use.",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()

                workflow.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertIn("Fixed in `abc123`.", client.replies[0])
                self.assertNotIn("Legacy handwritten reply", client.replies[0])

    def test_publish_github_thread_defer_uses_documented_reply_template(self):
        from gh_address_cr.core import workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append(body)
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                return True

        repo = "owner/repo"
        pr_number = "123"
        item = {
            "item_id": "github-thread:THREAD_1",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
            "state": "publish_ready",
            "status": "OPEN",
            "blocking": True,
            "accepted_response": {
                "resolution": "defer",
                "note": "Needs a follow-up.",
                "reply_markdown": "This needs a broader cleanup outside this PR.",
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
            },
        }
        expected = (
            "Thanks, this is valid feedback.\n"
            "\n"
            "Decision:\n"
            "- Marking as deferred (non-blocking for this PR) because: This needs a broader cleanup outside this PR.\n"
            "\n"
            "Follow-up plan:\n"
            "1. Track in `<issue_or_followup_pr>`.\n"
            "2. Scope: `<exact scope>`.\n"
            "3. Risk before follow-up: `<low/medium/high + short reason>`.\n"
            "\n"
            "If you prefer, I can bring this into the current PR instead.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()

                workflow.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertEqual(client.replies[0], expected)

    def test_publish_github_thread_response_fails_before_side_effect_without_reply_body(self):
        from gh_address_cr.core import workflow

        class FakeGitHubClient:
            def post_reply(self, repo, pr_number, thread_id, body):
                raise AssertionError("post_reply must not be called")

            def resolve_thread(self, repo, pr_number, thread_id):
                raise AssertionError("resolve_thread must not be called")

        repo = "owner/repo"
        pr_number = "123"
        item = {
            "item_id": "github-thread:THREAD_1",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
            "state": "publish_ready",
            "status": "OPEN",
            "blocking": True,
            "accepted_response": {
                "resolution": "clarify",
                "note": "Need maintainer input.",
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, item)

                with self.assertRaises(workflow.WorkflowError) as context:
                    workflow.publish_github_thread_responses(
                        repo,
                        pr_number,
                        github_client=FakeGitHubClient(),
                    )

                session = manager.load()
                self.assertEqual(context.exception.reason_code, "MISSING_PUBLISH_REPLY")
                self.assertEqual(session["items"]["github-thread:THREAD_1"]["state"], "publish_ready")


def stale_github_thread_item(item_id="github-thread:THREAD_STALE"):
    return {
        "item_id": item_id,
        "item_kind": "github_thread",
        "source": "github",
        "thread_id": item_id.removeprefix("github-thread:"),
        "title": "Stale review thread",
        "body": "Please add a null check.",
        "path": "src/example.py",
        "line": 10,
        "state": "stale",
        "status": "STALE",
        "blocking": True,
        "is_outdated": True,
        "allowed_actions": ["fix", "clarify", "defer", "reject"],
    }


class StaleThreadClaimabilityTests(unittest.TestCase):
    def write_session(self, repo: str, pr_number: str, item: dict):
        from gh_address_cr.core.session import SessionManager

        manager = SessionManager(repo, pr_number)
        session = manager.create(status="WAITING_FOR_CLASSIFICATION")
        session["items"] = {item["item_id"]: item}
        manager.save(session)
        return manager

    def test_stale_github_thread_is_claimable_by_triage_role(self):
        from gh_address_cr.core import workflow

        repo = "owner/repo"
        pr_number = "500"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, stale_github_thread_item())

                result = workflow.issue_action_request(repo, pr_number, role="triage", agent_id="triage-1")

                self.assertEqual(result["status"], "ACTION_REQUESTED")
                self.assertEqual(result["item_id"], "github-thread:THREAD_STALE")

    def test_stale_github_thread_with_classification_is_claimable_by_fixer_role(self):
        from gh_address_cr.core import workflow

        repo = "owner/repo"
        pr_number = "501"
        item = stale_github_thread_item()
        item["classification_evidence"] = {
            "classification": "fix",
            "event_type": "classification_recorded",
            "note": "Fix the null check.",
            "record_id": "rec-stale-1",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, item)

                result = workflow.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")

                self.assertEqual(result["status"], "ACTION_REQUESTED")
                self.assertEqual(result["item_id"], "github-thread:THREAD_STALE")

    def test_stale_thread_not_claimed_by_fixer_without_classification(self):
        from gh_address_cr.core import workflow

        repo = "owner/repo"
        pr_number = "502"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, stale_github_thread_item())

                with self.assertRaises(workflow.WorkflowError) as context:
                    workflow.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")

                self.assertEqual(context.exception.reason_code, "MISSING_CLASSIFICATION")

    def test_stale_thread_classification_keeps_stale_status_until_fixer_claim(self):
        from gh_address_cr.core import workflow

        repo = "owner/repo"
        pr_number = "503"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, stale_github_thread_item())

                triage = workflow.issue_action_request(repo, pr_number, role="triage", agent_id="triage-1")
                workflow.record_classification(
                    repo,
                    pr_number,
                    item_id="github-thread:THREAD_STALE",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect, needs null guard.",
                )

                session = manager.load()
                item = session["items"]["github-thread:THREAD_STALE"]
                self.assertEqual(session["leases"][triage["lease_id"]]["status"], "released")
                self.assertEqual(item["state"], "stale")
                self.assertEqual(item["status"], "STALE")
                self.assertNotIn("active_lease_id", item)

    def test_reclaim_expired_stale_thread_lease_restores_stale_state(self):
        from gh_address_cr.core import workflow

        repo = "owner/repo"
        pr_number = "504"
        now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
        item = stale_github_thread_item()
        item["classification_evidence"] = {
            "classification": "fix",
            "event_type": "classification_recorded",
            "note": "Fix the null check.",
            "record_id": "rec-stale-1",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, item)

                workflow.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1", now=now)
                reclaimed = workflow.reclaim_leases(repo, pr_number, now=now + timedelta(hours=2))

                session = manager.load()
                item = session["items"]["github-thread:THREAD_STALE"]
                self.assertEqual(reclaimed["expired_count"], 1)
                self.assertEqual(item["state"], "stale")
                self.assertEqual(item["status"], "STALE")
                self.assertNotIn("active_lease_id", item)

    def test_stale_thread_classify_submit_publish_final_gate_path(self):
        from gh_address_cr.core import gate, workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []
                self.resolved = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append((repo, pr_number, thread_id, body))
                return "https://github.test/reply/stale"

            def resolve_thread(self, repo, pr_number, thread_id):
                self.resolved.append((repo, pr_number, thread_id))
                return True

        repo = "owner/repo"
        pr_number = "505"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, stale_github_thread_item())
                workflow.record_classification(
                    repo,
                    pr_number,
                    item_id="github-thread:THREAD_STALE",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect, needs null guard.",
                )
                requested = workflow.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")
                request = json.loads(Path(requested["request_path"]).read_text(encoding="utf-8"))
                response_path = Path(tmp) / "stale-action-response.json"
                response_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "request_id": request["request_id"],
                            "lease_id": request["lease_id"],
                            "agent_id": "fixer-1",
                            "resolution": "fix",
                            "note": "Fixed stale thread issue.",
                            "files": ["src/example.py"],
                            "validation_commands": [
                                {
                                    "command": "python3 -m unittest tests.test_native_workflow.StaleThreadClaimabilityTests",
                                    "result": "passed",
                                }
                            ],
                            "fix_reply": {
                                "summary": "Fixed stale thread issue.",
                                "commit_hash": "abc123",
                                "files": ["src/example.py"],
                                "why": "The null guard now handles the stale review case.",
                            },
                        }
                    ),
                    encoding="utf-8",
                )

                accepted = workflow.submit_action_response(repo, pr_number, response_path=response_path)
                published = workflow.publish_github_thread_responses(
                    repo,
                    pr_number,
                    agent_id="agent-login",
                    github_client=FakeGitHubClient(),
                )
                result = gate.evaluate_final_gate(
                    manager.load(),
                    remote_threads=[{"id": "THREAD_STALE", "isResolved": True}],
                    current_login="agent-login",
                )

                self.assertEqual(accepted["status"], "ACTION_ACCEPTED")
                self.assertEqual(published["status"], "PUBLISH_COMPLETE")
                self.assertEqual(result.counts["unresolved_github_threads_count"], 0)
                self.assertEqual(result.counts["pending_review_count"], 0)
                self.assertEqual(result.counts["blocking_items_count"], 0)
                self.assertEqual(result.counts["github_threads_missing_reply_count"], 0)

    def test_stale_thread_classify_then_fixer_claim(self):
        from gh_address_cr.core import workflow

        repo = "owner/repo"
        pr_number = "506"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, stale_github_thread_item())

                workflow.issue_action_request(repo, pr_number, role="triage", agent_id="triage-1")
                classified = workflow.record_classification(
                    repo,
                    pr_number,
                    item_id="github-thread:THREAD_STALE",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect, needs null guard.",
                )
                fixer = workflow.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")

                session = manager.load()
                self.assertEqual(classified["status"], "CLASSIFICATION_RECORDED")
                self.assertEqual(fixer["status"], "ACTION_REQUESTED")
                self.assertEqual(fixer["item_id"], "github-thread:THREAD_STALE")
                item = session["items"]["github-thread:THREAD_STALE"]
                self.assertEqual(item["classification_evidence"]["classification"], "fix")


if __name__ == "__main__":
    unittest.main()
