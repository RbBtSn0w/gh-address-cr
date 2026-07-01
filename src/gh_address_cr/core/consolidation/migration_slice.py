"""Migration-slice contracts and pilot registration (feature 024, US2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gh_address_cr.core.consolidation.rollout import RollbackTrigger
from gh_address_cr.core.consolidation.types import Owner, RolloutStage, StateAxis


@dataclass(frozen=True)
class MigrationSlice:
    slice_id: str
    axes: tuple[StateAxis, ...]
    external_facts: tuple[str, ...]
    authoritative_projection: str
    deterministic_policy: str
    side_effect_boundary: str
    compatibility_projection: str | None
    replay_coverage: tuple[str, ...]
    supported_cohort: str
    rollback_trigger: RollbackTrigger
    state_space_reduction_axes: tuple[StateAxis, ...] = ()

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.slice_id.strip():
            raise ValueError("slice_id is required")
        if not self.axes:
            raise ValueError("axes are required")
        if not self.external_facts:
            raise ValueError("external_facts are required")
        if not self.authoritative_projection.strip():
            raise ValueError("authoritative_projection is required")
        if not self.deterministic_policy.strip():
            raise ValueError("deterministic_policy is required")
        if not self.side_effect_boundary.strip():
            raise ValueError("side_effect_boundary is required")
        if self.compatibility_projection is not None and not self.compatibility_projection.strip():
            raise ValueError("compatibility_projection must not be blank")
        if not self.replay_coverage:
            raise ValueError("replay_coverage is required")
        if not self.supported_cohort.strip():
            raise ValueError("supported_cohort is required")
        if not self.state_space_reduction_axes:
            raise ValueError("state_space_reduction_axes is required")
        if not set(self.state_space_reduction_axes).issubset(set(self.axes)):
            raise ValueError("state_space_reduction_axes must be a subset of axes")
        if not self.rollback_trigger.dimension.strip() or not self.rollback_trigger.threshold.strip():
            raise ValueError("rollback_trigger is required")

    def authority_for_cohort(self, cohort: str) -> Owner:
        return Owner.KERNEL if cohort == self.supported_cohort else Owner.LEGACY

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "axes": [axis.value for axis in self.axes],
            "external_facts": list(self.external_facts),
            "authoritative_projection": self.authoritative_projection,
            "deterministic_policy": self.deterministic_policy,
            "side_effect_boundary": self.side_effect_boundary,
            "compatibility_projection": self.compatibility_projection,
            "replay_coverage": list(self.replay_coverage),
            "supported_cohort": self.supported_cohort,
            "rollback_trigger": self.rollback_trigger.to_dict(),
            "state_space_reduction_axes": [axis.value for axis in self.state_space_reduction_axes],
        }


def _pilot_slice() -> MigrationSlice:
    return MigrationSlice(
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


_REGISTERED_SLICES: tuple[MigrationSlice, ...] = (_pilot_slice(),)


def registered_slices() -> tuple[MigrationSlice, ...]:
    return _REGISTERED_SLICES


def get_registered_slice(slice_id: str) -> MigrationSlice:
    for slice_ in _REGISTERED_SLICES:
        if slice_.slice_id == slice_id:
            return slice_
    raise KeyError(slice_id)


def default_rollout_slice_states() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "slice_id": slice_.slice_id,
            "stage": RolloutStage.SHADOW.value,
            "enabled": True,
            "evidence_ref": "evaluation.v1:run-cohort-abc",
            "deprecation_window_complete": False,
        }
        for slice_ in _REGISTERED_SLICES
    )
