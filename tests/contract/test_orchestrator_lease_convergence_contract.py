import inspect
import unittest
from unittest.mock import patch

from gh_address_cr.orchestrator import session as orchestrator_session
from gh_address_cr.orchestrator.harness import _record_reconciliation_event


class OrchestratorLeaseConvergenceContractTest(unittest.TestCase):
    def test_orchestrator_exposes_dispatch_projection_not_shadow_lease_policy(self):
        self.assertFalse(hasattr(orchestrator_session, "LeaseRecord"))
        self.assertFalse(hasattr(orchestrator_session.OrchestrationSession, "grant_lease"))
        self.assertFalse(hasattr(orchestrator_session.OrchestrationSession, "release_lease"))
        self.assertFalse(hasattr(orchestrator_session.OrchestrationSession, "validate_lease_for_submission"))

    def test_dispatch_receipt_references_canonical_runtime_truth_only(self):
        receipt = orchestrator_session.DispatchReceipt(
            item_id="finding-1",
            assigned_role="fixer",
            agent_id="orchestrator:run-1",
            lease_id="lease-runtime",
            request_id="req-runtime",
            runtime_revision=7,
            delivery_token="dispatch-token",
        )

        payload = receipt.to_dict()

        self.assertEqual(payload["schema_version"], "dispatch-receipt.v1")
        self.assertEqual(payload["lease_id"], "lease-runtime")
        self.assertEqual(payload["request_id"], "req-runtime")
        self.assertEqual(payload["runtime_revision"], 7)
        self.assertNotIn("expires_at", payload)
        self.assertNotIn("context_key", payload)
        self.assertNotIn("lease_status", payload)

    def test_session_source_contains_no_independent_lease_decision_axis(self):
        source = inspect.getsource(orchestrator_session)

        for forbidden in (
            "LEASE_TTL_MINUTES",
            "is_expired",
            "context_key",
            "force=True",
            "force: bool",
        ):
            self.assertNotIn(forbidden, source)

    def test_reconciliation_telemetry_is_bounded_and_identity_free(self):
        with patch("gh_address_cr.otel_tracing.add_current_span_event") as emit:
            _record_reconciliation_event({"retained": 2, "removed": 1, "runtime_revision": 42})

        emit.assert_called_once_with(
            "orchestrator.reconcile",
            {
                "gh_address_cr.orchestrator.reconcile.outcome": "repaired",
                "gh_address_cr.orchestrator.reconcile.count_bucket": "2-5",
            },
        )


if __name__ == "__main__":
    unittest.main()
