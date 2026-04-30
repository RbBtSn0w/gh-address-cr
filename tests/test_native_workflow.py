import json
import os
import tempfile
import unittest
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
                self.assertEqual(
                    client.replies[0], (repo, pr_number, "THREAD_1", "Can you confirm the intended behavior?")
                )
                self.assertEqual(client.resolved[0], (repo, pr_number, "THREAD_1"))
                self.assertEqual(updated["state"], "closed")
                self.assertEqual(updated["status"], "CLOSED")
                self.assertFalse(updated["blocking"])
                self.assertTrue(updated["handled"])
                self.assertEqual(updated["reply_url"], "https://github.test/reply")
                self.assertIn("reply_posted", event_types)
                self.assertIn("thread_resolved", event_types)
                self.assertIn("response_published", event_types)

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
            "- `src/example.py`: updated per CR scope\n"
            "\n"
            "Why this addresses the CR:\n"
            "- The input is now checked before use.\n"
            "- High-severity path validated with targeted regression checks.\n"
            "\n"
            "Validation:\n"
            "- `python3 -m unittest tests.test_example`\n"
            "- Result: passed\n"
            "\n"
            "If anything still looks off, I can follow up with a focused patch.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()

                workflow.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertEqual(client.replies[0], expected)

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


if __name__ == "__main__":
    unittest.main()
