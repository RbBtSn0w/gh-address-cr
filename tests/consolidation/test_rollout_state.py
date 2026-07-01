"""Contract tests for rollout-state.v1 (feature 024, US2/US3)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gh_address_cr.core.consolidation.optimization import default_hypothesis_states
from gh_address_cr.core.consolidation.rollout_state import RolloutSliceState, RolloutState
from gh_address_cr.core.consolidation.types import ROLLOUT_STATE_SCHEMA, RolloutStage


class RolloutStateTests(unittest.TestCase):
    def test_round_trips_through_atomic_load_and_write(self) -> None:
        state = RolloutState(
            slices=(
                RolloutSliceState(
                    slice_id="slice-check-state",
                    stage=RolloutStage.OPT_IN,
                    enabled=True,
                    evidence_ref="evaluation.v1:run-cohort-abc",
                    deprecation_window_complete=False,
                ),
            ),
            hypotheses=default_hypothesis_states(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-state.v1.json"
            state.write(path)
            loaded = RolloutState.load(path)
        self.assertEqual(loaded.to_dict()["schema"], ROLLOUT_STATE_SCHEMA)
        self.assertEqual(loaded.to_dict(), state.to_dict())

    def test_malformed_stage_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RolloutState.from_dict(
                {
                    "schema": ROLLOUT_STATE_SCHEMA,
                    "slices": [{"slice_id": "slice-check-state", "stage": "bogus", "enabled": True}],
                }
            )


if __name__ == "__main__":
    unittest.main()
