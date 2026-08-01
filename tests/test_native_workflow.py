import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from gh_address_cr.core import agent_protocol, publisher
from gh_address_cr.core.runtime_kernel.stack import project_stack_context


class UnstackedGitHubClient:
    def get_stack_context(self, repo, pr_number):
        return project_stack_context(
            {
                "schema_version": "stack_observation.v1",
                "availability": "absent",
                "repo": repo,
                "selected_pr_number": str(pr_number),
                "observed_at": "2026-08-01T12:00:00Z",
                "selected_pr": {
                    "position": 1,
                    "pr_number": str(pr_number),
                    "state": "OPEN",
                    "is_draft": False,
                    "base_ref_name": "main",
                    "head_ref_name": "feature/test",
                    "head_oid": "a" * 40,
                    "merge_queue_state": None,
                },
                "members": [],
            }
        )


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
    def setUp(self):
        patcher = patch(
            "gh_address_cr.core.agent_protocol.GitHubClient",
            return_value=UnstackedGitHubClient(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_session(self, repo: str, pr_number: str, item: dict):
        from gh_address_cr.core.session import SessionManager

        manager = SessionManager(repo, pr_number)
        session = manager.create(status="WAITING_FOR_CLASSIFICATION")
        session["items"] = {item["item_id"]: item}
        manager.save(session)
        return manager

    def test_record_classification_unblocks_fixer_action_request(self):
        from gh_address_cr.core import agent_protocol

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, open_item())

                classified = agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="local:1",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect.",
                )
                requested = agent_protocol.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")

                session = manager.load()
                evidence_rows = [
                    json.loads(line) for line in Path(session["ledger_path"]).read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(classified["status"], "CLASSIFICATION_RECORDED")
                self.assertEqual(session["items"]["local:1"]["classification_evidence"]["classification"], "fix")
                self.assertEqual(requested["status"], "ACTION_REQUESTED")
                self.assertEqual(evidence_rows[0]["event_type"], "classification_recorded")
                self.assertEqual(evidence_rows[0]["agent_id"], "triage-1")

    def test_action_request_refreshes_missing_stack_context_before_claim(self):
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context
        from tests.helpers import stack_observation

        repo = "octo/example"
        pr_number = "102"
        client = Mock()
        client.get_stack_context.return_value = project_stack_context(
            stack_observation(selected_pr_number=pr_number)
        )
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False),
                patch("gh_address_cr.core.agent_protocol.GitHubClient", create=True, return_value=client),
            ):
                self.write_session(repo, pr_number, open_item())
                agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="local:1",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect.",
                )

                requested = agent_protocol.issue_action_request(
                    repo,
                    pr_number,
                    role="fixer",
                    agent_id="fixer-1",
                )

                request = json.loads(Path(requested["request_path"]).read_text(encoding="utf-8"))
                self.assertEqual(request["repository_context"]["revision_binding"]["pr_number"], pr_number)
                self.assertEqual(request["repository_context"]["stack_context"]["availability"], "present")
                self.assertEqual(
                    request["repository_context"]["stack_context"]["selected_pr"]["head_ref_name"],
                    "feature/middle",
                )
                self.assertIn("checkout_stack", request["forbidden_actions"])
                self.assertIn("rebase_stack", request["forbidden_actions"])
                self.assertIn("push_stack", request["forbidden_actions"])
                client.get_stack_context.assert_called_once_with(repo, pr_number)

    def test_batch_action_requests_share_one_refreshed_stack_context(self):
        from gh_address_cr.core import agent_batch
        from tests.helpers import stack_observation

        repo = "octo/example"
        pr_number = "102"
        client = Mock()
        client.get_stack_context.return_value = project_stack_context(
            stack_observation(selected_pr_number=pr_number)
        )
        item = {
            **open_item("github-thread:THREAD_1"),
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False),
                patch("gh_address_cr.core.agent_protocol.GitHubClient", return_value=client),
            ):
                manager = self.write_session(repo, pr_number, item)

                requested = agent_batch.issue_batch_action_request(
                    repo,
                    pr_number,
                    agent_id="fixer-1",
                )

                session = manager.load()
                lease = session["leases"][requested["leased_items"][0]["lease_id"]]
                request = json.loads(Path(lease["request_path"]).read_text(encoding="utf-8"))
                self.assertEqual(request["repository_context"]["revision_binding"]["pr_number"], pr_number)
                self.assertEqual(
                    request["repository_context"]["stack_context"]["selected_pr"]["head_ref_name"],
                    "feature/middle",
                )
                self.assertIn("checkout_stack", request["forbidden_actions"])
                self.assertIn("rebase_stack", request["forbidden_actions"])
                self.assertIn("push_stack", request["forbidden_actions"])
                client.get_stack_context.assert_called_once_with(repo, pr_number)

    def test_stale_batch_context_releases_every_batch_lease(self):
        from gh_address_cr.core import agent_batch
        from gh_address_cr.core.errors import WorkflowError
        from gh_address_cr.core.session import SessionManager
        from tests.helpers import stack_observation

        class CurrentStackClient:
            def get_stack_context(self, repo, pr_number):
                changed = stack_observation(selected_pr_number=pr_number)
                changed["members"][1]["head_oid"] = "f" * 40
                return project_stack_context(changed)

        repo = "octo/example"
        pr_number = "102"
        items = {}
        for suffix in ("one", "two"):
            item = {
                **open_item(f"github-thread:{suffix}"),
                "item_kind": "github_thread",
                "source": "github",
                "thread_id": suffix,
                "classification_evidence": {
                    "event_type": "classification_recorded",
                    "classification": "fix",
                    "record_id": f"classification-{suffix}",
                },
            }
            items[item["item_id"]] = item

        initial_client = Mock()
        initial_client.get_stack_context.return_value = project_stack_context(
            stack_observation(selected_pr_number=pr_number)
        )
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False),
                patch("gh_address_cr.core.agent_protocol.GitHubClient", return_value=initial_client),
            ):
                manager = SessionManager(repo, pr_number)
                session = manager.create(status="WAITING_FOR_GATE")
                session["items"] = items
                manager.save(session)
                issued = agent_batch.issue_batch_action_request(repo, pr_number, agent_id="fixer-1")
                session = manager.load()
                requests = [
                    json.loads(Path(session["leases"][row["lease_id"]]["request_path"]).read_text(encoding="utf-8"))
                    for row in issued["leased_items"]
                ]
                response_path = Path(tmp) / "stale-batch.json"
                response_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "agent_id": "fixer-1",
                            "resolution": "fix",
                            "common": {
                                "files": ["src/example.py"],
                                "validation_commands": [{"command": "unit", "result": "passed"}],
                                "fix_reply": {"commit_hash": "abc1234"},
                            },
                            "items": [
                                {
                                    "request_id": request["request_id"],
                                    "lease_id": request["lease_id"],
                                    "item_id": request["item"]["item_id"],
                                    "summary": f"Fixed {request['item']['item_id']}.",
                                    "why": "The guarded path now handles the review concern.",
                                }
                                for request in requests
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

                with self.assertRaises(WorkflowError) as caught:
                    agent_batch.submit_batch_action_response(
                        repo,
                        pr_number,
                        batch_path=response_path,
                        github_client=CurrentStackClient(),
                    )

                self.assertEqual(caught.exception.reason_code, "STALE_REQUEST_CONTEXT")
                persisted = manager.load()
                for request in requests:
                    self.assertEqual(persisted["leases"][request["lease_id"]]["status"], "released")
                    item = persisted["items"][request["item"]["item_id"]]
                    self.assertEqual(item["state"], "open")
                    self.assertNotIn("active_lease_id", item)

    def test_batch_submit_uses_one_coherent_stack_observation(self):
        from gh_address_cr.core import agent_batch
        from gh_address_cr.core.session import SessionManager
        from tests.helpers import stack_observation

        repo = "octo/example"
        pr_number = "102"
        original = project_stack_context(stack_observation(selected_pr_number=pr_number))

        class MutatingAfterFirstReadClient:
            calls = 0

            def get_stack_context(self, repo, pr_number):
                self.calls += 1
                if self.calls == 1:
                    return original
                changed = stack_observation(selected_pr_number=pr_number)
                changed["members"][1]["head_oid"] = "f" * 40
                return project_stack_context(changed)

        items = {}
        for suffix in ("one", "two"):
            item = {
                **open_item(f"github-thread:{suffix}"),
                "item_kind": "github_thread",
                "source": "github",
                "thread_id": suffix,
                "classification_evidence": {
                    "event_type": "classification_recorded",
                    "classification": "fix",
                    "record_id": f"classification-{suffix}",
                },
            }
            items[item["item_id"]] = item

        initial_client = Mock()
        initial_client.get_stack_context.return_value = original
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False),
                patch("gh_address_cr.core.agent_protocol.GitHubClient", return_value=initial_client),
            ):
                manager = SessionManager(repo, pr_number)
                session = manager.create(status="WAITING_FOR_GATE")
                session["items"] = items
                manager.save(session)
                issued = agent_batch.issue_batch_action_request(repo, pr_number, agent_id="fixer-1")
                session = manager.load()
                requests = [
                    json.loads(Path(session["leases"][row["lease_id"]]["request_path"]).read_text(encoding="utf-8"))
                    for row in issued["leased_items"]
                ]
                response_path = Path(tmp) / "coherent-batch.json"
                response_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "agent_id": "fixer-1",
                            "resolution": "fix",
                            "common": {
                                "files": ["src/example.py"],
                                "validation_commands": [{"command": "unit", "result": "passed"}],
                                "fix_reply": {"commit_hash": "abc1234"},
                            },
                            "items": [
                                {
                                    "request_id": request["request_id"],
                                    "lease_id": request["lease_id"],
                                    "item_id": request["item"]["item_id"],
                                    "summary": f"Fixed {request['item']['item_id']}.",
                                    "why": "The guarded path now handles the review concern.",
                                }
                                for request in requests
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                current_client = MutatingAfterFirstReadClient()

                accepted = agent_batch.submit_batch_action_response(
                    repo,
                    pr_number,
                    batch_path=response_path,
                    github_client=current_client,
                )

                self.assertEqual(accepted["status"], "BATCH_ACTION_ACCEPTED")
                self.assertEqual(accepted["accepted_count"], 2)
                self.assertEqual(current_client.calls, 1)


    def test_unbound_request_is_rejected_when_submit_discovers_current_stack(self):
        from gh_address_cr.core.errors import WorkflowError
        from tests.helpers import stack_observation

        class UnavailableClient:
            def get_stack_context(self, repo, pr_number):
                return project_stack_context(
                    {
                        "schema_version": "stack_observation.v1",
                        "availability": "unavailable",
                        "repo": repo,
                        "selected_pr_number": str(pr_number),
                        "observed_at": "2026-08-01T12:00:00Z",
                        "members": [],
                    }
                )

        class StackedClient:
            def get_stack_context(self, repo, pr_number):
                return project_stack_context(stack_observation(selected_pr_number=pr_number))

        repo = "octo/example"
        pr_number = "102"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, open_item())
                agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="local:1",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect.",
                )
                requested = agent_protocol.issue_action_request(
                    repo,
                    pr_number,
                    role="fixer",
                    agent_id="fixer-1",
                    github_client=UnavailableClient(),
                )
                request = json.loads(Path(requested["request_path"]).read_text(encoding="utf-8"))
                self.assertNotIn("revision_binding", request["repository_context"])
                response_path = Path(tmp) / "unbound-stack-response.json"
                response_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "request_id": request["request_id"],
                            "lease_id": request["lease_id"],
                            "agent_id": "fixer-1",
                            "resolution": "fix",
                            "note": "Fixed the requested item.",
                            "files": ["src/example.py"],
                            "validation_commands": [{"command": "unit", "result": "passed"}],
                        }
                    ),
                    encoding="utf-8",
                )

                with self.assertRaises(WorkflowError) as caught:
                    agent_protocol.submit_action_response(
                        repo,
                        pr_number,
                        response_path=response_path,
                        github_client=StackedClient(),
                    )

                self.assertEqual(caught.exception.reason_code, "STALE_REQUEST_CONTEXT")
                session = manager.load()
                self.assertEqual(session["leases"][request["lease_id"]]["status"], "released")
                self.assertEqual(session["items"]["local:1"]["state"], "open")
                self.assertNotIn("active_lease_id", session["items"]["local:1"])

                refreshed = agent_protocol.issue_action_request(
                    repo,
                    pr_number,
                    role="fixer",
                    agent_id="fixer-1",
                    github_client=StackedClient(),
                )
                self.assertEqual(refreshed["status"], "ACTION_REQUESTED")
                self.assertNotEqual(refreshed["lease_id"], request["lease_id"])

    def test_unstacked_unbound_submit_does_not_construct_github_client(self):
        repo = "octo/example"
        pr_number = "102"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, open_item())
                agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="local:1",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect.",
                )
                requested = agent_protocol.issue_action_request(
                    repo,
                    pr_number,
                    role="fixer",
                    agent_id="fixer-1",
                    github_client=UnstackedGitHubClient(),
                )
                request = json.loads(Path(requested["request_path"]).read_text(encoding="utf-8"))
                self.assertEqual(request["repository_context"]["stack_context"]["availability"], "absent")
                self.assertNotIn("revision_binding", request["repository_context"])
                response_path = Path(tmp) / "unstacked-response.json"
                response_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "request_id": request["request_id"],
                            "lease_id": request["lease_id"],
                            "agent_id": "fixer-1",
                            "resolution": "fix",
                            "note": "Fixed the requested item.",
                            "files": ["src/example.py"],
                            "validation_commands": [{"command": "unit", "result": "passed"}],
                        }
                    ),
                    encoding="utf-8",
                )

                with patch(
                    "gh_address_cr.github.client.GitHubClient",
                    side_effect=AssertionError("ordinary unbound submit must not construct a GitHub client"),
                ):
                    accepted = agent_protocol.submit_action_response(
                        repo,
                        pr_number,
                        response_path=response_path,
                    )

                self.assertEqual(accepted["status"], "ACTION_ACCEPTED")

    def test_legacy_present_request_without_binding_is_rejected_after_unstacking(self):
        from gh_address_cr.core.errors import WorkflowError
        from gh_address_cr.core.models import ActionRequest
        from tests.helpers import stack_observation

        class StackedClient:
            def get_stack_context(self, repo, pr_number):
                return project_stack_context(stack_observation(selected_pr_number=pr_number))

        repo = "octo/example"
        pr_number = "102"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, open_item())
                agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="local:1",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect.",
                )
                requested = agent_protocol.issue_action_request(
                    repo,
                    pr_number,
                    role="fixer",
                    agent_id="fixer-1",
                    github_client=StackedClient(),
                )
                request_path = Path(requested["request_path"])
                request = json.loads(request_path.read_text(encoding="utf-8"))
                request["repository_context"].pop("revision_binding")
                request_path.write_text(json.dumps(request), encoding="utf-8")
                legacy_session = manager.load()
                legacy_session["leases"][request["lease_id"]]["request_hash"] = ActionRequest.from_dict(
                    request
                ).stable_hash()
                manager.save(legacy_session)
                response_path = Path(tmp) / "legacy-unbound-response.json"
                response_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "request_id": request["request_id"],
                            "lease_id": request["lease_id"],
                            "agent_id": "fixer-1",
                            "resolution": "fix",
                            "note": "Fixed the requested item.",
                            "files": ["src/example.py"],
                            "validation_commands": [{"command": "unit", "result": "passed"}],
                        }
                    ),
                    encoding="utf-8",
                )

                with self.assertRaises(WorkflowError) as caught:
                    agent_protocol.submit_action_response(
                        repo,
                        pr_number,
                        response_path=response_path,
                        github_client=UnstackedGitHubClient(),
                    )

                self.assertEqual(caught.exception.reason_code, "STALE_REQUEST_CONTEXT")
                session = manager.load()
                self.assertEqual(session["leases"][request["lease_id"]]["status"], "released")
                self.assertEqual(session["items"]["local:1"]["state"], "open")

    def test_known_stack_blocks_new_request_when_refresh_is_unavailable(self):
        from gh_address_cr.core.errors import WorkflowError
        from gh_address_cr.core.session import cache_pull_request_context
        from tests.helpers import stack_observation

        class UnavailableClient:
            def get_stack_context(self, repo, pr_number):
                return project_stack_context(
                    {
                        "schema_version": "stack_observation.v1",
                        "availability": "unavailable",
                        "repo": repo,
                        "selected_pr_number": str(pr_number),
                        "observed_at": "2026-08-01T12:01:00Z",
                        "members": [],
                    }
                )

        repo = "octo/example"
        pr_number = "102"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, open_item())
                session = manager.load()
                cache_pull_request_context(
                    session,
                    project_stack_context(stack_observation(selected_pr_number=pr_number)).to_dict(),
                )
                manager.save(session)
                agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="local:1",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect.",
                )

                with self.assertRaises(WorkflowError) as caught:
                    agent_protocol.issue_action_request(
                        repo,
                        pr_number,
                        role="fixer",
                        agent_id="fixer-1",
                        github_client=UnavailableClient(),
                    )

                self.assertEqual(caught.exception.reason_code, "STACK_CONTEXT_UNAVAILABLE")

    def test_record_classification_releases_active_triage_lease_for_fixer(self):
        from gh_address_cr.core import agent_protocol

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, open_item())

                triage = agent_protocol.issue_action_request(repo, pr_number, role="triage", agent_id="triage-1")
                classified = agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="local:1",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect.",
                )
                fixer = agent_protocol.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")

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
        from gh_address_cr.core import agent_protocol

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, open_item())

                with self.assertRaises(agent_protocol.WorkflowError) as context:
                    agent_protocol.record_classification(
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
        from gh_address_cr.core import agent_protocol

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, open_item())

                with self.assertRaises(agent_protocol.WorkflowError) as context:
                    agent_protocol.record_classification(
                        repo,
                        pr_number,
                        item_id="local:1",
                        classification="maybe",
                        agent_id="triage-1",
                        note="Unsupported.",
                    )

                self.assertEqual(context.exception.reason_code, "UNSUPPORTED_CLASSIFICATION")

    def test_publish_github_thread_response_posts_reply_resolves_and_closes_item(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
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

                result = publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

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

    def test_publish_mixed_review_threads_posts_distinct_targeted_replies(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
            def __init__(self):
                self.replies = []

            def viewer_login(self):
                return "agent-login"

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append((thread_id, body))
                return f"https://github.test/reply/{thread_id}"

            def resolve_thread(self, repo, pr_number, thread_id):
                return True

        repo = "owner/repo"
        pr_number = "123"
        first = {
            "item_id": "github-thread:THREAD_1",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_1",
            "body": "Why does this branch skip nil validation?",
            "state": "publish_ready",
            "status": "OPEN",
            "blocking": True,
            "accepted_response": {
                "resolution": "fix",
                "validation_commands": [{"command": "python3 -m unittest tests.test_shared", "result": "passed"}],
                "fix_reply": {
                    "commit_hash": "abc123",
                    "files": ["src/shared.py"],
                    "summary": "Restored nil validation.",
                    "why": "The nil-validation branch now rejects missing values before use.",
                },
            },
        }
        second = {
            "item_id": "github-thread:THREAD_2",
            "item_kind": "github_thread",
            "source": "github",
            "thread_id": "THREAD_2",
            "body": "Can this log expose private data?",
            "state": "publish_ready",
            "status": "OPEN",
            "blocking": True,
            "accepted_response": {
                "resolution": "fix",
                "validation_commands": [{"command": "python3 -m unittest tests.test_shared", "result": "passed"}],
                "fix_reply": {
                    "commit_hash": "abc123",
                    "files": ["src/shared.py"],
                    "summary": "Redacted private log data.",
                    "why": "The logging path now omits the sensitive token mentioned in this thread.",
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, first)
                session = manager.load()
                session["items"][second["item_id"]] = second
                manager.save(session)
                client = FakeGitHubClient()

                result = publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertEqual(result["status"], "PUBLISH_COMPLETE")
                self.assertEqual(result["published_count"], 2)
                self.assertEqual(len(client.replies), 2)
                bodies_by_thread_id = {thread_id: body for thread_id, body in client.replies}
                first_body = bodies_by_thread_id["THREAD_1"]
                second_body = bodies_by_thread_id["THREAD_2"]
                self.assertNotEqual(first_body, second_body)
                self.assertIn("The nil-validation branch now rejects missing values before use.", first_body)
                self.assertIn("The logging path now omits the sensitive token mentioned in this thread.", second_body)

    def test_submit_action_response_with_publish_posts_and_resolves_thread(self):
        from gh_address_cr.core import agent_protocol

        class FakeGitHubClient(UnstackedGitHubClient):
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
                request_info = agent_protocol.issue_action_request(repo, pr_number, role="fixer", agent_id="codex-1")
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

                result = agent_protocol.submit_action_response(
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
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
            def viewer_login(self):
                raise AssertionError("viewer_login should not be called without publish-ready work")

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, open_item())

                result = publisher.publish_github_thread_responses(repo, pr_number, github_client=FakeGitHubClient())

                self.assertEqual(result["status"], "NO_PUBLISH_READY_ITEMS")

    def test_publish_ready_thread_survives_remote_refresh_before_publish(self):
        from gh_address_cr.core import gate

        class FakeGitHubClient(UnstackedGitHubClient):
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

                result = publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                session = manager.load()
                self.assertEqual(result["status"], "PUBLISH_COMPLETE")
                self.assertEqual(client.replies[0][2], "THREAD_1")
                self.assertEqual(client.resolved[0], (repo, pr_number, "THREAD_1"))
                self.assertEqual(session["items"]["github-thread:THREAD_1"]["state"], "closed")

    def test_remote_refresh_recovers_publish_ready_from_accepted_evidence(self):
        from gh_address_cr.core import gate

        class FakeGitHubClient(UnstackedGitHubClient):
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
                result = publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                session = manager.load()
                self.assertEqual(result["status"], "PUBLISH_COMPLETE")
                self.assertEqual(client.replies[0][2], "THREAD_1")
                self.assertEqual(client.resolved[0], (repo, pr_number, "THREAD_1"))
                self.assertEqual(session["items"]["github-thread:THREAD_1"]["state"], "closed")

    def test_publish_github_thread_fix_uses_documented_reply_template(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
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
            "severity_evidence": {
                "value": "P1",
                "source": "github_first_comment",
                "raw_marker": "P1",
                "observed_from": "https://github.test/thread",
            },
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
            "Addressed in `abc123`.\n"
            "\n"
            "Review signal: `P1`\n"
            "\n"
            "- `src/example.py`: Added the missing input guard.\n"
            "- Why: The input is now checked before use.\n"
            "- Validation: `python3 -m unittest tests.test_example` passed\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()

                publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertEqual(client.replies[0], expected)
                self.assertNotIn("Severity:", client.replies[0])
                self.assertNotIn("Reviewer priority:", client.replies[0])

    def test_publish_github_thread_fix_hydrates_commit_evidence_at_publish_time(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
            def __init__(self):
                self.replies = []

            def viewer_login(self):
                return "agent-login"

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
                "files": ["AGENTS.md"],
                "validation_commands": [{"command": "python3 -m unittest tests.test_skill_docs", "result": "passed"}],
                "fix_reply": {
                    "summary": "Fixed the stale GitHub thread reference called out here.",
                    "files": ["AGENTS.md"],
                    "why": "The updated reference now matches the review-thread contract.",
                },
            },
        }
        expected = (
            "Addressed in `b35d5ef`.\n"
            "\n"
            "- `AGENTS.md`: Fixed the stale GitHub thread reference called out here.\n"
            "- Why: The updated reference now matches the review-thread contract.\n"
            "- Validation: `python3 -m unittest tests.test_skill_docs` passed\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, item)
                session = manager.load()
                session["commit_evidence"] = {"commit_hash": "b35d5ef24ea2d481ff29081d3927db2c2c6e7e7d"}
                manager.save(session)
                client = FakeGitHubClient()

                result = publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertEqual(result["status"], "PUBLISH_COMPLETE")
                self.assertEqual(client.replies[0], expected)

    def test_publish_github_thread_fix_reuses_git_head_commit_for_batch_publish(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
            def __init__(self):
                self.replies = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append(body)
                return f"https://github.test/reply/{thread_id}"

            def resolve_thread(self, repo, pr_number, thread_id):
                return True

        def item(thread_id):
            return {
                "item_id": f"github-thread:{thread_id}",
                "item_kind": "github_thread",
                "source": "github",
                "thread_id": thread_id,
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
                        "summary": f"Fixed {thread_id}.",
                        "files": ["src/example.py"],
                        "why": "The changed path now matches the review comment.",
                    },
                },
            }

        repo = "owner/repo"
        pr_number = "123"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, item("THREAD_1"))
                session = manager.load()
                session["items"]["github-thread:THREAD_2"] = item("THREAD_2")
                manager.save(session)
                client = FakeGitHubClient()
                git_result = type(
                    "GitResult",
                    (),
                    {"returncode": 0, "stdout": "abcdef1234567890\n"},
                )()

                with patch.object(publisher.subprocess, "run", return_value=git_result) as git_run:
                    result = publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertEqual(result["status"], "PUBLISH_COMPLETE")
                self.assertEqual(git_run.call_count, 1)
                self.assertEqual(len(client.replies), 2)
                self.assertTrue(all(reply.startswith("Addressed in `abcdef1`.") for reply in client.replies))

    def test_publish_github_thread_fix_without_severity_does_not_default_to_p2(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
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

                publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertNotIn("Severity:", client.replies[0])
                self.assertNotIn("Review signal:", client.replies[0])
                self.assertNotIn("Medium-severity path", client.replies[0])

    def test_publish_github_thread_fix_surfaces_raw_reviewer_priority(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
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
            "review_priority_evidence": {
                "value": "low",
                "source": "github_first_comment",
                "raw_marker": "Low Priority",
                "observed_from": "https://github.test/thread/1",
            },
            "state": "publish_ready",
            "status": "OPEN",
            "blocking": True,
            "publish_resolution": "fix",
            "accepted_response": {
                "resolution": "fix",
                "note": "Removed unreachable branch.",
                "files": ["src/gh_address_cr/cli.py"],
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                "fix_reply": {
                    "summary": "Removed unreachable fallback command branch.",
                    "commit_hash": "abc123",
                    "files": ["src/gh_address_cr/cli.py"],
                    "why": "The branch could not be reached after unsupported commands returned earlier.",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()

                publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertNotIn("Severity:", client.replies[0])
                self.assertNotIn("Reviewer priority:", client.replies[0])
                self.assertIn("Review signal: `Low Priority`", client.replies[0])
                self.assertIn("Reviewer-provided priority from github_first_comment", client.replies[0])
                self.assertNotIn("Risk note:", client.replies[0])

    def test_publish_github_thread_fix_with_legacy_unbacked_severity_does_not_default_to_p2(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
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

                publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertNotIn("Severity:", client.replies[0])
                self.assertNotIn("Medium-severity path", client.replies[0])

    def test_publish_github_thread_fix_uses_severity_specific_template_lines(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
            def __init__(self):
                self.replies = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append(body)
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                return True

        for severity in ("P1", "P2", "P3"):
            with self.subTest(severity=severity):
                repo = "owner/repo"
                pr_number = "123"
                item = {
                    "item_id": "github-thread:THREAD_1",
                    "item_kind": "github_thread",
                    "source": "github",
                    "thread_id": "THREAD_1",
                    "severity": severity,
                    "severity_evidence": {
                        "value": severity,
                        "source": "github_first_comment",
                        "raw_marker": severity,
                        "observed_from": "https://github.test/thread",
                    },
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

                        publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                        self.assertIn(f"Review signal: `{severity}`", client.replies[0])
                        self.assertNotIn("Severity:", client.replies[0])
                        self.assertNotIn("Reviewer priority:", client.replies[0])
                        self.assertNotIn("Risk note:", client.replies[0])

    def test_publish_github_thread_fix_ignores_reply_markdown_when_fix_reply_exists(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
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

                publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertIn("Addressed in `abc123`.", client.replies[0])
                self.assertNotIn("Legacy handwritten reply", client.replies[0])

    def test_publish_github_thread_defer_uses_documented_reply_template(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
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
            "If you prefer, I can bring this into the current PR instead.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()

                publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertEqual(client.replies[0], expected)

    def test_publish_github_thread_response_fails_before_side_effect_without_reply_body(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
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

                with self.assertRaises(agent_protocol.WorkflowError) as context:
                    publisher.publish_github_thread_responses(
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
    def setUp(self):
        patcher = patch(
            "gh_address_cr.core.agent_protocol.GitHubClient",
            return_value=UnstackedGitHubClient(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_session(self, repo: str, pr_number: str, item: dict):
        from gh_address_cr.core.session import SessionManager

        manager = SessionManager(repo, pr_number)
        session = manager.create(status="WAITING_FOR_CLASSIFICATION")
        session["items"] = {item["item_id"]: item}
        manager.save(session)
        return manager

    def test_stale_github_thread_is_claimable_by_triage_role(self):
        from gh_address_cr.core import agent_protocol

        repo = "owner/repo"
        pr_number = "500"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, stale_github_thread_item())

                result = agent_protocol.issue_action_request(repo, pr_number, role="triage", agent_id="triage-1")

                self.assertEqual(result["status"], "ACTION_REQUESTED")
                self.assertEqual(result["item_id"], "github-thread:THREAD_STALE")

    def test_stale_github_thread_with_classification_is_claimable_by_fixer_role(self):
        from gh_address_cr.core import agent_protocol

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

                result = agent_protocol.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")

                self.assertEqual(result["status"], "ACTION_REQUESTED")
                self.assertEqual(result["item_id"], "github-thread:THREAD_STALE")

    def test_stale_thread_not_claimed_by_fixer_without_classification(self):
        from gh_address_cr.core import agent_protocol

        repo = "owner/repo"
        pr_number = "502"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, stale_github_thread_item())

                with self.assertRaises(agent_protocol.WorkflowError) as context:
                    agent_protocol.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")

                self.assertEqual(context.exception.reason_code, "MISSING_CLASSIFICATION")

    def test_stale_thread_classification_keeps_stale_status_until_fixer_claim(self):
        from gh_address_cr.core import agent_protocol

        repo = "owner/repo"
        pr_number = "503"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, stale_github_thread_item())

                triage = agent_protocol.issue_action_request(repo, pr_number, role="triage", agent_id="triage-1")
                agent_protocol.record_classification(
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
        from gh_address_cr.core import agent_protocol, leases

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

                agent_protocol.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1", now=now)
                reclaimed = leases.reclaim_leases(repo, pr_number, now=now + timedelta(hours=2))

                session = manager.load()
                item = session["items"]["github-thread:THREAD_STALE"]
                self.assertEqual(reclaimed["expired_count"], 1)
                self.assertEqual(item["state"], "stale")
                self.assertEqual(item["status"], "STALE")
                self.assertNotIn("active_lease_id", item)

    def test_stale_thread_classify_submit_publish_final_gate_path(self):
        from gh_address_cr.core import gate

        class FakeGitHubClient(UnstackedGitHubClient):
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
                agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="github-thread:THREAD_STALE",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect, needs null guard.",
                )
                requested = agent_protocol.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")
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

                accepted = agent_protocol.submit_action_response(repo, pr_number, response_path=response_path)
                published = publisher.publish_github_thread_responses(
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

    def test_stale_thread_submit_recovers_when_original_lease_was_released(self):
        repo = "owner/repo"
        pr_number = "507"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, stale_github_thread_item())
                agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="github-thread:THREAD_STALE",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect, needs null guard.",
                )
                original = agent_protocol.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")
                original_request = json.loads(Path(original["request_path"]).read_text(encoding="utf-8"))
                original_response_path = Path(tmp) / "stale-released-lease-response.json"
                original_response_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "request_id": original_request["request_id"],
                            "lease_id": original_request["lease_id"],
                            "agent_id": "fixer-1",
                            "resolution": "fix",
                            "note": "Fixed stale thread issue after lease turnover.",
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
                            "item_id": "github-thread:THREAD_STALE",
                        }
                    ),
                    encoding="utf-8",
                )

                session = manager.load()
                from gh_address_cr.core import leases as lease_module

                released = lease_module.release_self_stale_lease(
                    session,
                    "github-thread:THREAD_STALE",
                    agent_id="fixer-1",
                )
                self.assertTrue(released)
                manager.save(session)

                refreshed = agent_protocol.issue_action_request(
                    repo,
                    pr_number,
                    role="fixer",
                    agent_id="fixer-1",
                )

                accepted = agent_protocol.submit_action_response(
                    repo,
                    pr_number,
                    response_path=original_response_path,
                )

                session = manager.load()
                self.assertEqual(refreshed["status"], "ACTION_REQUESTED")
                self.assertEqual(accepted["status"], "ACTION_ACCEPTED")
                self.assertEqual(accepted["item_id"], "github-thread:THREAD_STALE")
                self.assertEqual(session["items"]["github-thread:THREAD_STALE"]["state"], "publish_ready")

    def test_stale_thread_submit_recovers_when_original_lease_is_missing(self):
        repo = "owner/repo"
        pr_number = "508"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, stale_github_thread_item())
                agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="github-thread:THREAD_STALE",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect, needs null guard.",
                )
                original = agent_protocol.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")
                original_request = json.loads(Path(original["request_path"]).read_text(encoding="utf-8"))
                original_response_path = Path(tmp) / "stale-missing-lease-response.json"
                original_response_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "request_id": original_request["request_id"],
                            "lease_id": original_request["lease_id"],
                            "agent_id": "fixer-1",
                            "resolution": "fix",
                            "note": "Fixed stale thread issue after lease turnover.",
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
                            "item_id": "github-thread:THREAD_STALE",
                        }
                    ),
                    encoding="utf-8",
                )

                session = manager.load()
                from gh_address_cr.core import leases as lease_module

                released = lease_module.release_self_stale_lease(
                    session,
                    "github-thread:THREAD_STALE",
                    agent_id="fixer-1",
                )
                self.assertTrue(released)
                session["leases"].pop(original["lease_id"], None)
                manager.save(session)

                refreshed = agent_protocol.issue_action_request(
                    repo,
                    pr_number,
                    role="fixer",
                    agent_id="fixer-1",
                )

                accepted = agent_protocol.submit_action_response(
                    repo,
                    pr_number,
                    response_path=original_response_path,
                )

                session = manager.load()
                self.assertEqual(refreshed["status"], "ACTION_REQUESTED")
                self.assertEqual(accepted["status"], "ACTION_ACCEPTED")
                self.assertEqual(accepted["item_id"], "github-thread:THREAD_STALE")
                self.assertEqual(session["items"]["github-thread:THREAD_STALE"]["state"], "publish_ready")

    def test_stale_thread_classify_then_fixer_claim(self):
        from gh_address_cr.core import agent_protocol

        repo = "owner/repo"
        pr_number = "506"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, stale_github_thread_item())

                agent_protocol.issue_action_request(repo, pr_number, role="triage", agent_id="triage-1")
                classified = agent_protocol.record_classification(
                    repo,
                    pr_number,
                    item_id="github-thread:THREAD_STALE",
                    classification="fix",
                    agent_id="triage-1",
                    note="Real defect, needs null guard.",
                )
                fixer = agent_protocol.issue_action_request(repo, pr_number, role="fixer", agent_id="fixer-1")

                session = manager.load()
                self.assertEqual(classified["status"], "CLASSIFICATION_RECORDED")
                self.assertEqual(fixer["status"], "ACTION_REQUESTED")
                self.assertEqual(fixer["item_id"], "github-thread:THREAD_STALE")
                item = session["items"]["github-thread:THREAD_STALE"]
                self.assertEqual(item["classification_evidence"]["classification"], "fix")

    def test_publish_github_thread_responses_does_not_include_efficiency_summary(self):
        from gh_address_cr.core import publisher
        from gh_address_cr.core.telemetry import SessionTelemetry

        class FakeGitHubClient(UnstackedGitHubClient):
            def __init__(self):
                self.replies = []

            def viewer_login(self):
                return "agent-login"

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
                "resolution": "clarify",
                "note": "Need maintainer input.",
                "reply_markdown": "Can you confirm the intended behavior?",
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()

                SessionTelemetry.reset()
                tracker = SessionTelemetry.get_instance()
                tracker.configure_context(repo, pr_number)
                tracker.record("npm install", 100.0, 105.0, 0)
                SessionTelemetry.reset()

                publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                self.assertEqual(len(client.replies), 1)
                self.assertNotIn("Agent Efficiency Summary", client.replies[0])
                self.assertNotIn("1 tools invoked", client.replies[0])

    def test_publish_waits_briefly_for_remote_thread_resolution_to_settle(self):
        from gh_address_cr.core import publisher

        class FakeGitHubClient(UnstackedGitHubClient):
            def __init__(self):
                self.replies = []
                self.resolved = []
                self.list_threads_calls = 0

            def viewer_login(self):
                return "agent-login"

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append((repo, pr_number, thread_id, body))
                return "https://github.test/reply"

            def resolve_thread(self, repo, pr_number, thread_id):
                self.resolved.append((repo, pr_number, thread_id))
                return True

            def list_threads(self, repo, pr_number):
                self.list_threads_calls += 1
                if self.list_threads_calls == 1:
                    return [{"id": "THREAD_1", "isResolved": False, "isOutdated": False}]
                return [{"id": "THREAD_1", "isResolved": True, "isOutdated": False}]

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
                "resolution": "fix",
                "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
                "fix_reply": {
                    "commit_hash": "abc123",
                    "files": ["src/example.py"],
                    "summary": "Fixed thread issue.",
                    "why": "The guarded path now covers the review case.",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self.write_session(repo, pr_number, item)
                client = FakeGitHubClient()
                with patch("gh_address_cr.core.publisher.time.sleep") as sleep:
                    result = publisher.publish_github_thread_responses(repo, pr_number, github_client=client)

                session = manager.load()
                self.assertEqual(result["status"], "PUBLISH_COMPLETE")
                self.assertEqual(session["items"]["github-thread:THREAD_1"]["state"], "closed")
                self.assertEqual(client.list_threads_calls, 2)
                sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
