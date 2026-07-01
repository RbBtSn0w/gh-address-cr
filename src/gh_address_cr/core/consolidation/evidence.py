"""Read-only evaluation evidence adapter for rollout gates (feature 024)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from gh_address_cr.core.consolidation.types import RolloutStage
from gh_address_cr.core.protocol_codes import INSUFFICIENT_EVIDENCE


class RolloutEvidenceStatus(str, Enum):
    INSUFFICIENT = "insufficient"
    PROVISIONAL = "provisional"
    DURABLE = "durable"


@dataclass(frozen=True)
class RolloutEvidence:
    status: RolloutEvidenceStatus
    reason_code: str
    reference: str | None = None
    details: tuple[str, ...] = ()
    suggested_stage: RolloutStage = RolloutStage.SHADOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "reference": self.reference,
            "details": list(self.details),
            "suggested_stage": self.suggested_stage.value,
        }


def evaluation_to_rollout_evidence(result: Mapping[str, Any]) -> RolloutEvidence:
    """Map feature-023 evaluation output to rollout evidence only.

    Missing or non-durable evaluation results become ``INSUFFICIENT_EVIDENCE``.
    The adapter is read-only and never writes into session or final-gate truth.
    """

    evaluation_id = str(result.get("evaluation_id") or "").strip()
    reference = f"evaluation.v1:{evaluation_id}" if evaluation_id else None
    durable_state = str(result.get("durable_state") or "")
    durable_reason = str(result.get("durable_reason") or "")
    if durable_state == "verified" and durable_reason == "DURABLE_VERIFIED":
        return RolloutEvidence(
            status=RolloutEvidenceStatus.DURABLE,
            reason_code="DURABLE_VERIFIED",
            reference=reference,
            details=("feature-023 evaluation verified",),
            suggested_stage=RolloutStage.OPT_IN,
        )

    provisional_state = str(result.get("provisional_state") or "")
    if provisional_state == "verified":
        return RolloutEvidence(
            status=RolloutEvidenceStatus.PROVISIONAL,
            reason_code="PROVISIONAL_EVIDENCE",
            reference=reference,
            details=("feature-023 evaluation is provisional only",),
            suggested_stage=RolloutStage.OPT_IN,
        )

    return RolloutEvidence(
        status=RolloutEvidenceStatus.INSUFFICIENT,
        reason_code=INSUFFICIENT_EVIDENCE,
        reference=reference,
        details=("feature-023 evaluation missing or not durable",),
        suggested_stage=RolloutStage.SHADOW,
    )
