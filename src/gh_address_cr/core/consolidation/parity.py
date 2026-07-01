"""Side-effect-free parity observation (feature 024, US1).

``ParityObserver`` replays the same runtime facts through the legacy projection
and a registered pluggable candidate-projection hook, then compares projections,
policy decisions, and *planned* commands. It executes zero external side effects:
no GitHub reply, resolve, review submission, or PR mutation, and no command plan
is ever executed. The result is a versioned ``parity-report.v1`` artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gh_address_cr.core.consolidation.types import PARITY_REPORT_SCHEMA
from gh_address_cr.core.runtime_kernel.commands import plan_review_commands
from gh_address_cr.core.runtime_kernel.events import sort_runtime_facts
from gh_address_cr.core.runtime_kernel.identity import planned_command_digest
from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
from gh_address_cr.core.runtime_kernel.projections import ReviewProjection, project_review_threads

JsonDict = dict[str, Any]

# A candidate projection has the same signature as ``project_review_threads``.
CandidateProjection = Callable[[Any], ReviewProjection]


@dataclass(frozen=True)
class ParityDifference:
    """One dimension in which legacy and candidate behaviour diverged."""

    dimension: str  # "projection" | "decision" | "command_plan"
    detail: str

    def to_dict(self) -> JsonDict:
        return {"dimension": self.dimension, "detail": self.detail}


@dataclass(frozen=True)
class ParityObservation:
    """A ``parity-report.v1`` comparison result. Never executes side effects."""

    slice_id: str
    fact_digest: str
    projection_match: bool
    decision_match: bool
    command_plan_match: bool
    side_effects_executed: int = 0
    differences: tuple[ParityDifference, ...] = ()

    def to_dict(self) -> JsonDict:
        return {
            "schema": PARITY_REPORT_SCHEMA,
            "slice_id": self.slice_id,
            "fact_digest": self.fact_digest,
            "projection_match": self.projection_match,
            "decision_match": self.decision_match,
            "command_plan_match": self.command_plan_match,
            "side_effects_executed": self.side_effects_executed,
            "differences": [difference.to_dict() for difference in self.differences],
        }


def _fact_digest(facts: Any) -> str:
    ordered = [fact.to_dict() for fact in sort_runtime_facts(tuple(facts))]
    encoded = json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _command_plan_keys(projection: ReviewProjection) -> list[tuple[str, str]]:
    """Compare plans by idempotency key + payload digest, never by execution."""
    decision = evaluate_review_policy(projection)
    keys: list[tuple[str, str]] = []
    for command in plan_review_commands(projection, decision):
        digest = planned_command_digest(
            command_kind=command.command_kind,
            reason_code=command.reason_code,
            item_id=command.item_id,
            payload=command.payload,
        )
        keys.append((command.idempotency_key, digest))
    return sorted(keys)


class ParityObserver:
    """Compares a slice's candidate path against the legacy path, read-only."""

    def __init__(self, github_client: Any | None = None) -> None:
        # Stored for interface symmetry only; parity never performs GitHub IO.
        self._github_client = github_client
        self._candidates: dict[str, CandidateProjection] = {}

    def register_candidate(self, slice_id: str, candidate: CandidateProjection) -> None:
        self._candidates[slice_id] = candidate

    def observe(self, slice_id: str, facts: Any) -> ParityObservation:
        candidate = self._candidates.get(slice_id)
        if candidate is None:
            raise KeyError(f"no candidate projection registered for slice {slice_id!r}")

        legacy_projection = project_review_threads(facts)
        candidate_projection = candidate(facts)

        differences: list[ParityDifference] = []

        projection_match = legacy_projection.to_dict() == candidate_projection.to_dict()
        if not projection_match:
            differences.append(ParityDifference("projection", "legacy and candidate projections differ"))

        legacy_decision = evaluate_review_policy(legacy_projection).to_dict()
        candidate_decision = evaluate_review_policy(candidate_projection).to_dict()
        decision_match = legacy_decision == candidate_decision
        if not decision_match:
            differences.append(ParityDifference("decision", "legacy and candidate policy decisions differ"))

        legacy_plan = _command_plan_keys(legacy_projection)
        candidate_plan = _command_plan_keys(candidate_projection)
        command_plan_match = legacy_plan == candidate_plan
        if not command_plan_match:
            differences.append(ParityDifference("command_plan", "legacy and candidate planned commands differ"))

        return ParityObservation(
            slice_id=slice_id,
            fact_digest=_fact_digest(facts),
            projection_match=projection_match,
            decision_match=decision_match,
            command_plan_match=command_plan_match,
            side_effects_executed=0,
            differences=tuple(differences),
        )
