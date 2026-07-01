"""Deterministic rollout gate and rollback policy (feature 024)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from gh_address_cr.core.consolidation.evidence import RolloutEvidence, RolloutEvidenceStatus
from gh_address_cr.core.consolidation.types import ROLLOUT_STAGE_ORDER, RolloutStage
from gh_address_cr.core.protocol_codes import (
    DEPRECATION_WINDOW_OPEN,
    INSUFFICIENT_EVIDENCE,
    PARITY_DIFF,
    QUALITY_REGRESSION,
)


@dataclass(frozen=True)
class RollbackTrigger:
    dimension: str
    threshold: str
    reversal_stage: RolloutStage

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "threshold": self.threshold,
            "reversal_stage": self.reversal_stage.value,
        }


@dataclass(frozen=True)
class RolloutDecision:
    allowed: bool
    reason_code: str
    next_stage: RolloutStage

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "next_stage": self.next_stage.value,
        }


def _stage_index(stage: RolloutStage) -> int:
    return ROLLOUT_STAGE_ORDER.index(stage)


class RolloutPolicy:
    """A deterministic stage-transition function over rollout evidence."""

    def evaluate(
        self,
        *,
        current_stage: RolloutStage,
        target_stage: RolloutStage,
        evidence: RolloutEvidence | None = None,
        parity_differences: Sequence[str] = (),
        deprecation_window_complete: bool = False,
        quality_regression: bool = False,
        rollback_trigger: RollbackTrigger | None = None,
        rollback_trigger_breached: bool = False,
    ) -> RolloutDecision:
        if rollback_trigger_breached and rollback_trigger is not None:
            return RolloutDecision(True, "ROLLBACK_TRIGGER_BREACHED", rollback_trigger.reversal_stage)

        if quality_regression:
            return RolloutDecision(False, QUALITY_REGRESSION, current_stage)

        if target_stage == current_stage:
            return RolloutDecision(True, "NO_CHANGE", current_stage)

        if _stage_index(target_stage) < _stage_index(current_stage):
            return RolloutDecision(True, "ROLLBACK_REQUESTED", target_stage)

        if parity_differences and target_stage in {RolloutStage.DEFAULT, RolloutStage.DEPRECATING, RolloutStage.DELETED}:
            return RolloutDecision(False, PARITY_DIFF, current_stage)

        if target_stage == RolloutStage.DEFAULT:
            if evidence is None or evidence.status != RolloutEvidenceStatus.DURABLE:
                return RolloutDecision(False, INSUFFICIENT_EVIDENCE, current_stage)
            return RolloutDecision(True, "ROLLOUT_STAGE_CHANGED", target_stage)

        if target_stage == RolloutStage.DELETED:
            if not deprecation_window_complete:
                return RolloutDecision(False, DEPRECATION_WINDOW_OPEN, current_stage)
            if evidence is None or evidence.status != RolloutEvidenceStatus.DURABLE:
                return RolloutDecision(False, INSUFFICIENT_EVIDENCE, current_stage)
            return RolloutDecision(True, "ROLLOUT_STAGE_CHANGED", target_stage)

        if target_stage == RolloutStage.OPT_IN and current_stage == RolloutStage.SHADOW:
            return RolloutDecision(True, "ROLLOUT_STAGE_CHANGED", target_stage)

        return RolloutDecision(True, "ROLLOUT_STAGE_CHANGED", target_stage)
