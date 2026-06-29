import unittest

from gh_address_cr.core.models import (
    DeliverySlice,
    LeaseRecoveryState,
    LogicValidationSignal,
    TelemetryCoverageState,
    WorkItemHandlingBoundary,
)


class RuntimeComplexityModelTests(unittest.TestCase):
    def test_work_item_handling_boundary_round_trips_contract_fields(self):
        boundary = WorkItemHandlingBoundary.from_dict(
            {
                "boundary_id": "github-thread-fix",
                "item_kinds": ["github_thread"],
                "applicability": "matched",
                "priority": 10,
                "required_evidence": ["classification", "files", "validation", "reply"],
                "completion_criteria": ["accepted_evidence", "published_reply", "resolved_thread", "final_gate"],
                "terminal_failure_reasons": ["UNSUPPORTED_WORK_ITEM", "BOUNDARY_CONFLICT"],
                "next_actions": ["issue_action_request"],
            }
        )

        payload = boundary.to_dict()

        self.assertEqual(payload["boundary_id"], "github-thread-fix")
        self.assertEqual(payload["item_kinds"], ["github_thread"])
        self.assertEqual(payload["priority"], 10)
        self.assertIn("classification", payload["required_evidence"])
        self.assertIn("BOUNDARY_CONFLICT", payload["terminal_failure_reasons"])

    def test_lease_recovery_state_exposes_agent_safe_outcomes(self):
        state = LeaseRecoveryState.from_dict(
            {
                "lease_id": "lease_123",
                "item_id": "github-thread:THREAD_1",
                "agent_id": "codex-fixer-1",
                "request_id": "req_123",
                "request_hash": "hash-current",
                "lease_status": "expired",
                "item_state": "open",
                "recovery_outcome": "reclaim",
                "reason_code": "EXPIRED_LEASE_RECLAIMABLE",
                "resume_command": "gh-address-cr agent next owner/repo 123 --role fixer --agent-id codex-fixer-1",
            }
        )

        payload = state.to_dict()

        self.assertEqual(payload["recovery_outcome"], "reclaim")
        self.assertEqual(payload["reason_code"], "EXPIRED_LEASE_RECLAIMABLE")
        self.assertIn("agent next", payload["resume_command"])

    def test_telemetry_coverage_state_preserves_budget_and_diagnostics(self):
        state = TelemetryCoverageState.from_dict(
            {
                "coverage_label": "partial",
                "sources": ["runtime"],
                "write_status": "slow",
                "diagnostics": ["TELEMETRY_OVERHEAD_EXCEEDED"],
                "privacy_status": "safe",
                "report_path": "efficiency_report.json",
                "overhead_ms": 275,
            }
        )

        payload = state.to_dict()

        self.assertEqual(payload["coverage_label"], "partial")
        self.assertEqual(payload["sources"], ["runtime"])
        self.assertEqual(payload["overhead_ms"], 275)
        self.assertIn("TELEMETRY_OVERHEAD_EXCEEDED", payload["diagnostics"])

    def test_logic_validation_signal_defaults_to_advisory_unless_blocking(self):
        signal = LogicValidationSignal.from_dict(
            {
                "signal_id": "signal_123",
                "item_id": "github-thread:THREAD_1",
                "signal_type": "low_confidence_advisory",
                "confidence": "low",
                "explanation": "The rationale may be thin but required evidence is present.",
                "recommended_action": "continue",
                "gate_effect": "advisory",
            }
        )

        payload = signal.to_dict()

        self.assertEqual(payload["signal_type"], "low_confidence_advisory")
        self.assertEqual(payload["gate_effect"], "advisory")
        self.assertEqual(payload["recommended_action"], "continue")

    def test_delivery_slice_records_independent_acceptance_evidence(self):
        delivery_slice = DeliverySlice.from_dict(
            {
                "slice_id": "phase-1",
                "scope": "Work item boundary MVP",
                "included_contracts": ["work-item-handling", "lease-recovery"],
                "acceptance_evidence": ["tests/test_work_item_handling_boundaries.py"],
                "remaining_scope": ["telemetry boundary", "logic validation"],
            }
        )

        payload = delivery_slice.to_dict()

        self.assertEqual(payload["slice_id"], "phase-1")
        self.assertIn("work-item-handling", payload["included_contracts"])
        self.assertIn("logic validation", payload["remaining_scope"])


if __name__ == "__main__":
    unittest.main()
