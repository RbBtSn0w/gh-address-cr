import unittest
from datetime import datetime, timedelta, timezone
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


if __name__ == "__main__":
    unittest.main()
