import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.leases import (
    LeaseSubmissionError as RuntimeLeaseSubmissionError,
)
from gh_address_cr.core.leases import (
    claim_lease as runtime_claim_lease,
)
from gh_address_cr.core.leases import (
    submit_lease as runtime_submit_lease,
)
from gh_address_cr.core.session import SessionManager
from gh_address_cr.orchestrator.harness import handle_agent_orchestrate
from gh_address_cr.orchestrator.session import DispatchValidationError, OrchestrationSession
from tests.test_native_workflow import UnstackedGitHubClient


class TestLeaseScheduling(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": self.temp_dir.name}, clear=False)
        self.env_patch.start()
        self.session = OrchestrationSession(run_id="test-run", repo="owner/repo", pr_number="123")

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_dispatch_validation_delegates_lease_state_to_runtime(self):
        receipt = self.session.project_dispatch(
            item_id="finding-1",
            role="fixer",
            agent_id="orchestrator:test-run",
            lease_id="lease-1",
            request_id="req-1",
            runtime_revision=2,
        )
        runtime_state = {
            "leases": {
                "lease-1": {
                    "lease_id": "lease-1",
                    "item_id": "finding-1",
                    "request_id": "req-1",
                    "status": "active",
                }
            }
        }

        self.assertIs(self.session.validate_dispatch("finding-1", receipt.delivery_token, runtime_state), receipt)

        runtime_state["leases"]["lease-1"]["status"] = "released"
        with self.assertRaises(DispatchValidationError):
            self.session.validate_dispatch("finding-1", receipt.delivery_token, runtime_state)

    def test_reconciliation_removes_stale_dispatch_without_releasing_runtime_lease(self):
        self.session.project_dispatch(
            item_id="finding-1",
            role="fixer",
            agent_id="orchestrator:test-run",
            lease_id="lease-1",
            request_id="req-1",
            runtime_revision=2,
        )
        runtime_state = {"leases": {}}

        result = self.session.reconcile_dispatches(runtime_state, runtime_revision=3)

        self.assertEqual(result, {"retained": 0, "removed": 1, "runtime_revision": 3})
        self.assertEqual(runtime_state["leases"], {})


class TestLeaseReleaseOrderingOnSubmit(unittest.TestCase):
    def setUp(self):
        self.repo = "owner/repo"
        self.pr = "123"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.stack_client_patch = patch(
            "gh_address_cr.core.agent_protocol_submission.GitHubClient",
            return_value=UnstackedGitHubClient(),
        )
        self.stack_client_patch.start()
        self.env_patch = patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": self.temp_dir.name}, clear=False)
        self.env_patch.start()

        manager = SessionManager(self.repo, self.pr)
        session = manager.create(status="ACTIVE")
        session["items"] = {
            "finding-1": {
                "item_id": "finding-1",
                "item_kind": "local_finding",
                "source": "local",
                "title": "Example",
                "body": "Body",
                "path": "src/a.py",
                "line": 1,
                "state": "open",
                "status": "OPEN",
                "blocking": True,
                "handled": False,
                "allowed_actions": ["fix", "clarify", "defer", "reject"],
                "classification_evidence": {
                    "event_type": "classification_recorded",
                    "classification": "fix",
                    "note": "ok",
                    "record_id": "rec-1",
                },
            }
        }
        manager.save(session)

        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)
        self.assertEqual(handle_agent_orchestrate("step", [self.repo, self.pr, "--role", "fixer"]), 0)

        from gh_address_cr.orchestrator.session import load_orchestration_session

        orch = load_orchestration_session(self.repo, self.pr)
        self.delivery_token = orch.active_dispatches["finding-1"].delivery_token
        self.response = Path(self.temp_dir.name) / "response.json"
        self.response.write_text(
            json.dumps({"evidence": {"files": [], "validation_commands": [], "note": "n", "fix_reply": {}}}) + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.stack_client_patch.stop()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    @patch("gh_address_cr.orchestrator.harness.parse_and_validate_response", return_value={})
    @patch("gh_address_cr.orchestrator.harness.agent_protocol.submit_action_response")
    def test_lease_release_occurs_only_after_successful_runtime_submission(self, mock_submit, _mock_parse):
        from gh_address_cr.orchestrator.session import load_orchestration_session

        mock_submit.side_effect = WorkflowError(
            status="ACTION_REJECTED",
            reason_code="STALE_REQUEST_CONTEXT",
            exit_code=5,
            waiting_on="action_response",
            message="stale",
        )
        rc_fail = handle_agent_orchestrate(
            "submit",
            [
                self.repo,
                self.pr,
                "--item-id",
                "finding-1",
                "--token",
                self.delivery_token,
                "--input",
                str(self.response),
            ],
        )
        self.assertEqual(rc_fail, 2)
        self.assertIn("finding-1", load_orchestration_session(self.repo, self.pr).active_dispatches)

        mock_submit.side_effect = None
        mock_submit.return_value = {"status": "ACTION_ACCEPTED"}
        rc_ok = handle_agent_orchestrate(
            "submit",
            [
                self.repo,
                self.pr,
                "--item-id",
                "finding-1",
                "--token",
                self.delivery_token,
                "--input",
                str(self.response),
            ],
        )
        self.assertEqual(rc_ok, 0)
        self.assertNotIn("finding-1", load_orchestration_session(self.repo, self.pr).active_dispatches)


class TestRuntimeLeaseRecoveryAudit(unittest.TestCase):
    def test_expired_submission_records_recovery_audit_event(self):
        session = {"items": {}, "leases": {}, "lease_events": []}
        item = {"item_id": "finding-1", "path": "src/a.py", "state": "claimed"}
        session["items"][item["item_id"]] = item
        lease = runtime_claim_lease(
            session,
            item,
            agent_id="codex-fixer-1",
            role="fixer",
            request_hash="hash-current",
            lease_id="lease-expired",
            ttl_seconds=1,
            now=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        )

        with self.assertRaises(RuntimeLeaseSubmissionError):
            runtime_submit_lease(
                session,
                lease.lease_id,
                agent_id="codex-fixer-1",
                role="fixer",
                item_id=item["item_id"],
                request_hash="hash-current",
                now=datetime(2026, 4, 24, 12, 0, 2, tzinfo=timezone.utc),
            )

        recovery_events = [
            event for event in session["lease_events"] if event["event_type"] == "lease_recovery_calculated"
        ]
        self.assertEqual(len(recovery_events), 1)
        self.assertEqual(recovery_events[0]["recovery_outcome"], "renew")
        self.assertEqual(recovery_events[0]["reason_code"], "EXPIRED_LEASE_RENEWABLE")


if __name__ == "__main__":
    unittest.main()
