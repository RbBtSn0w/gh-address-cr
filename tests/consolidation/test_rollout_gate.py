"""Gate tests for rollout transitions (feature 024, US2)."""

from __future__ import annotations

import unittest

from gh_address_cr.core.consolidation.evidence import RolloutEvidence, RolloutEvidenceStatus
from gh_address_cr.core.consolidation.rollout import RollbackTrigger, RolloutPolicy
from gh_address_cr.core.consolidation.types import RolloutStage
from gh_address_cr.core.protocol_codes import DEPRECATION_WINDOW_OPEN, INSUFFICIENT_EVIDENCE, PARITY_DIFF


class RolloutGateTests(unittest.TestCase):
    def test_shadow_to_opt_in_allows_provisional_evidence(self) -> None:
        policy = RolloutPolicy()
        decision = policy.evaluate(
            current_stage=RolloutStage.SHADOW,
            target_stage=RolloutStage.OPT_IN,
            evidence=RolloutEvidence(
                status=RolloutEvidenceStatus.PROVISIONAL,
                reason_code="PROVISIONAL_EVIDENCE",
                reference="evaluation.v1:run-cohort-abc",
            ),
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.next_stage, RolloutStage.OPT_IN)

    def test_opt_in_to_default_requires_durable_evidence(self) -> None:
        policy = RolloutPolicy()
        decision = policy.evaluate(
            current_stage=RolloutStage.OPT_IN,
            target_stage=RolloutStage.DEFAULT,
            evidence=RolloutEvidence(
                status=RolloutEvidenceStatus.PROVISIONAL,
                reason_code="PROVISIONAL_EVIDENCE",
                reference="evaluation.v1:run-cohort-abc",
            ),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, INSUFFICIENT_EVIDENCE)

    def test_unexplained_parity_diff_blocks_default(self) -> None:
        policy = RolloutPolicy()
        decision = policy.evaluate(
            current_stage=RolloutStage.OPT_IN,
            target_stage=RolloutStage.DEFAULT,
            evidence=RolloutEvidence(
                status=RolloutEvidenceStatus.DURABLE,
                reason_code="DURABLE_VERIFIED",
                reference="evaluation.v1:run-cohort-abc",
            ),
            parity_differences=("projection",),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, PARITY_DIFF)

    def test_deleted_requires_completed_deprecation_window(self) -> None:
        policy = RolloutPolicy()
        decision = policy.evaluate(
            current_stage=RolloutStage.DEPRECATING,
            target_stage=RolloutStage.DELETED,
            evidence=RolloutEvidence(
                status=RolloutEvidenceStatus.DURABLE,
                reason_code="DURABLE_VERIFIED",
                reference="evaluation.v1:run-cohort-abc",
            ),
            deprecation_window_complete=False,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, DEPRECATION_WINDOW_OPEN)

    def test_rollback_trigger_breach_uses_reversal_stage(self) -> None:
        policy = RolloutPolicy()
        decision = policy.evaluate(
            current_stage=RolloutStage.DEFAULT,
            target_stage=RolloutStage.DEFAULT,
            rollback_trigger=RollbackTrigger(
                dimension="quality",
                threshold="regression",
                reversal_stage=RolloutStage.OPT_IN,
            ),
            rollback_trigger_breached=True,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.next_stage, RolloutStage.OPT_IN)


if __name__ == "__main__":
    unittest.main()
