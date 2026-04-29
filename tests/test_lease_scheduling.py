import unittest
import tempfile
import os
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from gh_address_cr.core.session import SessionManager
from gh_address_cr.core.workflow import WorkflowError
from gh_address_cr.orchestrator.harness import handle_agent_orchestrate
from gh_address_cr.orchestrator.session import OrchestrationSession, LeaseConflictError, ExpiredLeaseError


class TestLeaseScheduling(unittest.TestCase):
    def setUp(self):
        self.session = OrchestrationSession(run_id="test-run", repo="owner/repo", pr_number="123")

    def test_rejecting_conflicting_lease_claims(self):
        # T014: If item has an active lease, new claim is rejected
        self.session.grant_lease("finding-1", "fixer")
        with self.assertRaises(LeaseConflictError):
            self.session.grant_lease("finding-1", "triage")

    def test_reclaiming_expired_leases(self):
        # T015: If lease TTL is passed, it can be reclaimed
        # Force a lease that expired 1 minute ago
        expired_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.session.grant_lease("finding-1", "fixer")
        self.session.active_leases["finding-1"].expires_at = expired_time

        # This should succeed by reclaiming the stale lease
        new_lease = self.session.grant_lease("finding-1", "triage")
        self.assertEqual(new_lease.assigned_role, "triage")

    def test_rejecting_response_with_expired_token(self):
        # T015a: If agent submits with expired token, fail loud
        lease = self.session.grant_lease("finding-1", "fixer")
        self.session.active_leases["finding-1"].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        with self.assertRaises(ExpiredLeaseError):
            self.session.validate_lease_for_submission("finding-1", lease.lease_token)

    def test_verifier_reject_returns_item_to_blocked_state(self):
        # T015b: If verifier rejects, item status rolls back and lease is released
        lease = self.session.grant_lease("finding-1", "verifier")
        self.assertIn("finding-1", self.session.active_leases)

        self.session.handle_verifier_reject("finding-1", lease.lease_token)
        self.assertNotIn("finding-1", self.session.active_leases)

    def test_concurrent_issuance_for_non_conflicting_files(self):
        # T026: Test concurrent issuance for non-conflicting files
        # One in file_a, one in file_b
        self.session.grant_lease("finding-1", "fixer", context_key="file_a.py")
        lease2 = self.session.grant_lease("finding-2", "fixer", context_key="file_b.py")
        self.assertEqual(lease2.item_id, "finding-2")

    def test_parallel_claim_blocking_for_overlapping_keys(self):
        # T027: Test parallel claim blocking for overlapping file keys
        self.session.grant_lease("finding-1", "fixer", context_key="common.py")
        with self.assertRaises(LeaseConflictError) as cm:
            self.session.grant_lease("finding-2", "triage", context_key="common.py")
        self.assertIn("overlapping context key 'common.py'", str(cm.exception))


class TestLeaseReleaseOrderingOnSubmit(unittest.TestCase):
    def setUp(self):
        self.repo = "owner/repo"
        self.pr = "123"
        self.temp_dir = tempfile.TemporaryDirectory()
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
        self.lease_token = orch.active_leases["finding-1"].lease_token
        self.response = Path(self.temp_dir.name) / "response.json"
        self.response.write_text(
            json.dumps({"evidence": {"files": [], "validation_commands": [], "note": "n", "fix_reply": {}}})
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    @patch("gh_address_cr.orchestrator.harness.parse_and_validate_response", return_value={})
    @patch("gh_address_cr.orchestrator.harness.workflow.submit_action_response")
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
                self.lease_token,
                "--input",
                str(self.response),
            ],
        )
        self.assertEqual(rc_fail, 2)
        self.assertIn("finding-1", load_orchestration_session(self.repo, self.pr).active_leases)

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
                self.lease_token,
                "--input",
                str(self.response),
            ],
        )
        self.assertEqual(rc_ok, 0)
        self.assertNotIn("finding-1", load_orchestration_session(self.repo, self.pr).active_leases)


if __name__ == "__main__":
    unittest.main()
