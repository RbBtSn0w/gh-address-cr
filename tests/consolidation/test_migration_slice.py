"""Contract tests for migration slices (feature 024, US2)."""

from __future__ import annotations

import unittest

from gh_address_cr.core.consolidation.authority_map import RuntimeAuthorityMap, derive_authority_map
from gh_address_cr.core.consolidation.migration_slice import (
    MigrationSlice,
    RollbackTrigger,
    get_registered_slice,
    registered_slices,
)
from gh_address_cr.core.consolidation.types import CompatibilityDirection, Owner, RolloutStage, StateAxis


class MigrationSliceTests(unittest.TestCase):
    def _slice(self, **overrides):
        base = dict(
            slice_id="slice-check-state",
            axes=(StateAxis.CHECK,),
            external_facts=("review_thread_observed",),
            authoritative_projection="runtime_kernel.projections.project_review_threads",
            deterministic_policy="runtime_kernel.policies.evaluate_review_policy",
            side_effect_boundary="runtime_kernel.commands.plan_review_commands",
            compatibility_projection="legacy.review_projection",
            replay_coverage=("tests/consolidation/test_parity_observation.py",),
            supported_cohort="github-review-thread",
            rollback_trigger=RollbackTrigger(
                dimension="parity",
                threshold="no unexplained diffs",
                reversal_stage=RolloutStage.SHADOW,
            ),
            state_space_reduction_axes=(StateAxis.CHECK,),
        )
        base.update(overrides)
        return MigrationSlice(**base)

    def test_incomplete_slice_cannot_advance_past_shadow(self) -> None:
        with self.assertRaises(ValueError):
            self._slice(external_facts=())

    def test_state_space_reduction_is_required(self) -> None:
        with self.assertRaises(ValueError):
            self._slice(state_space_reduction_axes=())

    def test_unsupported_cohort_routes_to_legacy(self) -> None:
        slice_ = self._slice()
        self.assertEqual(slice_.authority_for_cohort("github-review-thread"), Owner.KERNEL)
        self.assertEqual(slice_.authority_for_cohort("other-cohort"), Owner.LEGACY)

    def test_pilot_slice_is_registered(self) -> None:
        pilot = get_registered_slice("slice-check-state")
        self.assertEqual(pilot.slice_id, "slice-check-state")
        self.assertEqual(pilot.axes, (StateAxis.CHECK,))
        self.assertIn(pilot, registered_slices())

    def test_duplicate_owner_reduction_is_explicitly_modeled(self) -> None:
        authority = derive_authority_map(
            "3.2.2",
            {StateAxis.CHECK: (Owner.KERNEL, CompatibilityDirection.LEGACY_FROM_KERNEL, "slice-check-state")},
        )
        self.assertIsInstance(authority, RuntimeAuthorityMap)

    def test_invalid_slice_id_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._slice(slice_id="")


if __name__ == "__main__":
    unittest.main()
