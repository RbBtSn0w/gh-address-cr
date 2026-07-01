"""Optimization-hypothesis contract tests (feature 024, US3)."""

from __future__ import annotations

import unittest

from gh_address_cr.core.consolidation.optimization import (
    default_hypothesis_states,
    default_optimization_hypotheses,
)
from gh_address_cr.core.consolidation.rollout_state import RolloutState
from gh_address_cr.core.consolidation.types import RolloutStage
from gh_address_cr.core.protocol_codes import INSUFFICIENT_EVIDENCE


class OptimizationHypothesisTests(unittest.TestCase):
    def test_three_hypotheses_move_independently(self) -> None:
        state = RolloutState(hypotheses=default_hypothesis_states())
        updated = state.with_hypothesis_stage("output_truncation", RolloutStage.OPT_IN)
        self.assertEqual(updated.hypothesis_for("output_truncation").stage, RolloutStage.OPT_IN)
        self.assertEqual(updated.hypothesis_for("command_session").stage, RolloutStage.SHADOW)
        self.assertEqual(updated.hypothesis_for("workflow_surface_removal").stage, RolloutStage.SHADOW)

    def test_output_truncation_is_not_default_until_gate_passes(self) -> None:
        hypothesis = next(item for item in default_optimization_hypotheses() if item.hypothesis_id == "output_truncation")
        decision = hypothesis.evaluate_transition(RolloutStage.DEFAULT, durable_evidence=False, quality_regression=False)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, INSUFFICIENT_EVIDENCE)

    def test_non_session_path_remains_available_while_command_session_is_below_default(self) -> None:
        hypothesis = next(item for item in default_optimization_hypotheses() if item.hypothesis_id == "command_session")
        self.assertEqual(hypothesis.safe_fallback, "non-session path")
        self.assertTrue(hypothesis.non_session_path_available())


if __name__ == "__main__":
    unittest.main()
