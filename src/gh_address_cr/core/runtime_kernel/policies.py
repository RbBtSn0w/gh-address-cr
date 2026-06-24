"""Policy decisions over runtime-kernel projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gh_address_cr.core.runtime_kernel.projections import ReviewProjection

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class PolicyDecision:
    status: str
    reason_codes: tuple[str, ...]
    item_ids: tuple[str, ...] = ()
    next_action: str = "none"

    def to_dict(self) -> JsonDict:
        return {
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "item_ids": list(self.item_ids),
            "next_action": self.next_action,
        }


def _has_blocking_diagnostic(projection: ReviewProjection) -> bool:
    return any(diagnostic.get("severity") == "blocking" for diagnostic in projection.diagnostics)


def evaluate_review_policy(projection: ReviewProjection) -> PolicyDecision:
    if _has_blocking_diagnostic(projection):
        reason_codes = tuple(
            str(diagnostic.get("reason_code") or "KERNEL_PROJECTION_CONTRADICTION")
            for diagnostic in projection.diagnostics
            if diagnostic.get("severity") == "blocking"
        )
        return PolicyDecision(
            status="blocked",
            reason_codes=reason_codes,
            next_action="stop_and_inspect_kernel_facts",
        )

    actionable_ids = tuple(sorted(set(projection.active_item_ids).union(projection.evidence_pending_item_ids)))
    if actionable_ids:
        return PolicyDecision(
            status="ready_for_action",
            reason_codes=("REVIEW_THREAD_ACTION_REQUIRED",),
            item_ids=actionable_ids,
            next_action="repair_review_threads",
        )

    if projection.waiting_item_ids:
        return PolicyDecision(
            status="waiting_for_external_input",
            reason_codes=("WAITING_FOR_EXTERNAL_INPUT",),
            item_ids=projection.waiting_item_ids,
            next_action="wait_for_external_input",
        )

    return PolicyDecision(
        status="final_gate_eligible",
        reason_codes=("FINAL_GATE_ELIGIBLE",),
        next_action="run_final_gate",
    )
