"""Optimization hypotheses and their independent rollout state (feature 024)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gh_address_cr.core.consolidation.types import RolloutStage
from gh_address_cr.core.protocol_codes import INSUFFICIENT_EVIDENCE, QUALITY_REGRESSION


@dataclass(frozen=True)
class HypothesisState:
    hypothesis_id: str
    stage: RolloutStage
    enabled: bool
    safe_fallback: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "stage": self.stage.value,
            "enabled": self.enabled,
            "safe_fallback": self.safe_fallback,
        }


@dataclass(frozen=True)
class HypothesisTransitionDecision:
    allowed: bool
    reason_code: str
    next_stage: RolloutStage

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "next_stage": self.next_stage.value,
        }


@dataclass(frozen=True)
class OptimizationHypothesis:
    hypothesis_id: str
    expected_benefit: str
    protected_guardrails: tuple[str, ...]
    cohort_rules: str
    staged_enablement: RolloutStage
    stop_condition: str
    rollback_action: str
    safe_fallback: str

    def evaluate_transition(
        self,
        target_stage: RolloutStage,
        *,
        durable_evidence: bool,
        quality_regression: bool,
    ) -> HypothesisTransitionDecision:
        if quality_regression:
            return HypothesisTransitionDecision(False, QUALITY_REGRESSION, self.staged_enablement)
        if target_stage == RolloutStage.DEFAULT and not durable_evidence:
            return HypothesisTransitionDecision(False, INSUFFICIENT_EVIDENCE, self.staged_enablement)
        return HypothesisTransitionDecision(True, "ROLLOUT_STAGE_CHANGED", target_stage)

    def non_session_path_available(self) -> bool:
        return "non-session" in self.safe_fallback or self.hypothesis_id != "command_session"

    def to_state(self) -> HypothesisState:
        return HypothesisState(
            hypothesis_id=self.hypothesis_id,
            stage=self.staged_enablement,
            enabled=self.staged_enablement != RolloutStage.SHADOW,
            safe_fallback=self.safe_fallback,
        )


def default_optimization_hypotheses() -> tuple[OptimizationHypothesis, ...]:
    return (
        OptimizationHypothesis(
            hypothesis_id="output_truncation",
            expected_benefit="token reduction",
            protected_guardrails=("quality", "public output contract"),
            cohort_rules="supported review-thread cohort",
            staged_enablement=RolloutStage.SHADOW,
            stop_condition="unexplained quality regression",
            rollback_action="restore verbose output",
            safe_fallback="--full output remains default",
        ),
        OptimizationHypothesis(
            hypothesis_id="command_session",
            expected_benefit="latency and orchestration simplification",
            protected_guardrails=("operational health", "non-session availability"),
            cohort_rules="supported review flows only",
            staged_enablement=RolloutStage.SHADOW,
            stop_condition="command-session unavailable or unhealthy",
            rollback_action="restore non-session path",
            safe_fallback="non-session path",
        ),
        OptimizationHypothesis(
            hypothesis_id="workflow_surface_removal",
            expected_benefit="lower maintenance complexity",
            protected_guardrails=("public contract stability", "parity"),
            cohort_rules="default after full deprecation window",
            staged_enablement=RolloutStage.SHADOW,
            stop_condition="legacy workflow surface still required",
            rollback_action="restore legacy workflow surface",
            safe_fallback="legacy workflow surface remains available",
        ),
    )


def default_hypothesis_states() -> tuple[HypothesisState, ...]:
    return tuple(hypothesis.to_state() for hypothesis in default_optimization_hypotheses())
