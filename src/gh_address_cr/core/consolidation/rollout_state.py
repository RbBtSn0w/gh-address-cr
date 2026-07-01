"""Versioned rollout-state.v1 control artifact (feature 024)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from gh_address_cr.core.consolidation.migration_slice import default_rollout_slice_states
from gh_address_cr.core.consolidation.optimization import HypothesisState, default_hypothesis_states
from gh_address_cr.core.consolidation.types import ROLLOUT_STATE_SCHEMA, RolloutStage
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.paths import state_dir


@dataclass(frozen=True)
class RolloutSliceState:
    slice_id: str
    stage: RolloutStage
    enabled: bool
    evidence_ref: str | None = None
    deprecation_window_complete: bool = False

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RolloutSliceState":
        stage = RolloutStage(str(payload.get("stage") or ""))
        return cls(
            slice_id=str(payload.get("slice_id") or ""),
            stage=stage,
            enabled=bool(payload.get("enabled", False)),
            evidence_ref=None if payload.get("evidence_ref") is None else str(payload.get("evidence_ref")),
            deprecation_window_complete=bool(payload.get("deprecation_window_complete", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "stage": self.stage.value,
            "enabled": self.enabled,
            "evidence_ref": self.evidence_ref,
            "deprecation_window_complete": self.deprecation_window_complete,
        }


@dataclass(frozen=True)
class RolloutState:
    slices: tuple[RolloutSliceState, ...] = ()
    hypotheses: tuple[HypothesisState, ...] = ()
    schema: str = ROLLOUT_STATE_SCHEMA

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RolloutState":
        if str(payload.get("schema") or "") != ROLLOUT_STATE_SCHEMA:
            raise ValueError("unsupported rollout-state schema")
        slices_payload = payload.get("slices")
        if slices_payload is None:
            slices_payload = default_rollout_slice_states()
        else:
            slices_payload = _merge_slice_payloads(slices_payload, default_rollout_slice_states())
        hypotheses_payload = payload.get("hypotheses")
        if hypotheses_payload is None:
            hypotheses_payload = [state.to_dict() for state in default_hypothesis_states()]
        else:
            hypotheses_payload = _merge_hypothesis_payloads(
                hypotheses_payload,
                [state.to_dict() for state in default_hypothesis_states()],
            )
        slices = tuple(RolloutSliceState.from_dict(row) for row in slices_payload)
        hypotheses = tuple(
            HypothesisState(
                hypothesis_id=str(row.get("hypothesis_id") or ""),
                stage=RolloutStage(str(row.get("stage") or "")),
                enabled=bool(row.get("enabled", False)),
                safe_fallback=str(row.get("safe_fallback") or ""),
            )
            for row in hypotheses_payload
        )
        state = cls(slices=slices, hypotheses=hypotheses)
        state.validate()
        return state

    @classmethod
    def load(cls, path: str | Path) -> "RolloutState":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def default(cls) -> "RolloutState":
        return cls.from_dict(
            {
                "schema": ROLLOUT_STATE_SCHEMA,
                "slices": default_rollout_slice_states(),
                "hypotheses": [state.to_dict() for state in default_hypothesis_states()],
            }
        )

    def validate(self) -> None:
        slice_ids = [slice_state.slice_id for slice_state in self.slices]
        if len(slice_ids) != len(set(slice_ids)):
            raise ValueError("slice ids must be unique")
        hypothesis_ids = [state.hypothesis_id for state in self.hypotheses]
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            raise ValueError("hypothesis ids must be unique")
        for slice_state in self.slices:
            if not isinstance(slice_state.stage, RolloutStage):
                raise ValueError("invalid slice stage")
        for hypothesis in self.hypotheses:
            if not isinstance(hypothesis.stage, RolloutStage):
                raise ValueError("invalid hypothesis stage")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "slices": [slice_state.to_dict() for slice_state in self.slices],
            "hypotheses": [state.to_dict() for state in self.hypotheses],
        }

    def write(self, path: str | Path) -> None:
        write_json_atomic(path, self.to_dict())

    def slice_for(self, slice_id: str) -> RolloutSliceState:
        for slice_state in self.slices:
            if slice_state.slice_id == slice_id:
                return slice_state
        raise KeyError(slice_id)

    def hypothesis_for(self, hypothesis_id: str) -> HypothesisState:
        for hypothesis in self.hypotheses:
            if hypothesis.hypothesis_id == hypothesis_id:
                return hypothesis
        raise KeyError(hypothesis_id)

    def with_slice_stage(
        self,
        slice_id: str,
        stage: RolloutStage,
        *,
        enabled: bool | None = None,
        evidence_ref: str | None = None,
        deprecation_window_complete: bool | None = None,
    ) -> "RolloutState":
        updated: list[RolloutSliceState] = []
        found = False
        for slice_state in self.slices:
            if slice_state.slice_id != slice_id:
                updated.append(slice_state)
                continue
            found = True
            updated.append(
                RolloutSliceState(
                    slice_id=slice_state.slice_id,
                    stage=stage,
                    enabled=slice_state.enabled if enabled is None else enabled,
                    evidence_ref=slice_state.evidence_ref if evidence_ref is None else evidence_ref,
                    deprecation_window_complete=(
                        slice_state.deprecation_window_complete
                        if deprecation_window_complete is None
                        else deprecation_window_complete
                    ),
                )
            )
        if not found:
            raise KeyError(slice_id)
        return RolloutState(slices=tuple(updated), hypotheses=self.hypotheses)

    def with_hypothesis_stage(
        self,
        hypothesis_id: str,
        stage: RolloutStage,
        *,
        enabled: bool | None = None,
        safe_fallback: str | None = None,
    ) -> "RolloutState":
        updated: list[HypothesisState] = []
        found = False
        for hypothesis in self.hypotheses:
            if hypothesis.hypothesis_id != hypothesis_id:
                updated.append(hypothesis)
                continue
            found = True
            updated.append(
                HypothesisState(
                    hypothesis_id=hypothesis.hypothesis_id,
                    stage=stage,
                    enabled=hypothesis.enabled if enabled is None else enabled,
                    safe_fallback=hypothesis.safe_fallback if safe_fallback is None else safe_fallback,
                )
            )
        if not found:
            raise KeyError(hypothesis_id)
        return RolloutState(slices=self.slices, hypotheses=tuple(updated))


def rollout_state_path() -> Path:
    return state_dir() / "consolidation" / "rollout-state.v1.json"


def load_or_default(path: str | Path | None = None) -> RolloutState:
    target = Path(path) if path is not None else rollout_state_path()
    if not target.exists():
        return RolloutState.default()
    return RolloutState.load(target)


def default_rollout_state() -> RolloutState:
    return RolloutState.default()


def _merge_slice_payloads(
    existing_payloads: Any,
    default_payloads: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    existing_rows = [dict(row) for row in existing_payloads]
    existing_ids = {str(row.get("slice_id") or "") for row in existing_rows if row.get("slice_id")}
    merged = list(existing_rows)
    merged.extend(default_row for default_row in default_payloads if default_row["slice_id"] not in existing_ids)
    return merged


def _merge_hypothesis_payloads(
    existing_payloads: Any,
    default_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_rows = [dict(row) for row in existing_payloads]
    existing_ids = {str(row.get("hypothesis_id") or "") for row in existing_rows if row.get("hypothesis_id")}
    merged = list(existing_rows)
    merged.extend(default_row for default_row in default_payloads if default_row["hypothesis_id"] not in existing_ids)
    return merged
