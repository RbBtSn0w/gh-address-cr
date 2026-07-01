"""Rollback contract tests (feature 024, US2)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gh_address_cr.core.consolidation.rollout import RollbackTrigger, RolloutPolicy
from gh_address_cr.core.consolidation.rollout_state import RolloutSliceState, RolloutState
from gh_address_cr.core.consolidation.types import RolloutStage


class RollbackTests(unittest.TestCase):
    def test_breached_trigger_reverts_stage_without_rewriting_runtime_truth(self) -> None:
        policy = RolloutPolicy()
        state = RolloutState(
            slices=(
                RolloutSliceState(
                    slice_id="slice-check-state",
                    stage=RolloutStage.DEFAULT,
                    enabled=True,
                    evidence_ref="evaluation.v1:run-cohort-abc",
                    deprecation_window_complete=False,
                ),
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_path = root / "session.json"
            evidence_path = root / "evidence.jsonl"
            session_path.write_text("session-truth", encoding="utf-8")
            evidence_path.write_text("evidence-truth", encoding="utf-8")
            state_path = root / "rollout-state.v1.json"
            state.write(state_path)

            result = policy.evaluate(
                current_stage=RolloutStage.DEFAULT,
                target_stage=RolloutStage.DEFAULT,
                rollback_trigger=RollbackTrigger(
                    dimension="operational_health",
                    threshold="error-rate > 5%",
                    reversal_stage=RolloutStage.OPT_IN,
                ),
                rollback_trigger_breached=True,
            )
            self.assertTrue(result.allowed)
            state = state.with_slice_stage("slice-check-state", result.next_stage)
            state.write(state_path)

            self.assertEqual(session_path.read_text(encoding="utf-8"), "session-truth")
            self.assertEqual(evidence_path.read_text(encoding="utf-8"), "evidence-truth")
            self.assertEqual(RolloutState.load(state_path).slice_for("slice-check-state").stage, RolloutStage.OPT_IN)


if __name__ == "__main__":
    unittest.main()
