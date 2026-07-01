"""Explicit deprecation inventory for consolidation cleanup (feature 024)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gh_address_cr.core.consolidation.types import DEPRECATION_INVENTORY_SCHEMA, ROLLOUT_STAGE_ORDER, RolloutStage


@dataclass(frozen=True)
class DeprecationEntry:
    kind: str
    target: str
    replaced_by: str
    slice_id: str
    contract_boundary: str
    removable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "replaced_by": self.replaced_by,
            "slice_id": self.slice_id,
            "contract_boundary": self.contract_boundary,
            "removable": self.removable,
        }


@dataclass(frozen=True)
class DeprecationInventory:
    entries: tuple[DeprecationEntry, ...]

    def validate(self, *, slice_stage: RolloutStage, deprecation_window_complete: bool) -> None:
        for entry in self.entries:
            if not entry.removable:
                continue
            if ROLLOUT_STAGE_ORDER.index(slice_stage) < ROLLOUT_STAGE_ORDER.index(RolloutStage.DEPRECATING) or not deprecation_window_complete:
                raise ValueError("deletion entries require a deprecating slice with a completed window")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DEPRECATION_INVENTORY_SCHEMA,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def default_deprecation_inventory() -> DeprecationInventory:
    return DeprecationInventory(
        entries=(
            DeprecationEntry(
                kind="duplicate_model",
                target="core.workflow_matching",
                replaced_by="core.runtime_kernel.projections",
                slice_id="slice-check-state",
                contract_boundary="kernel projection is authoritative; legacy kept until deprecation window completes",
                removable=False,
            ),
            DeprecationEntry(
                kind="compatibility_shim",
                target="workflow.py legacy branch",
                replaced_by="core.consolidation.rollout",
                slice_id="slice-check-state",
                contract_boundary="replacement proven by parity and rollout gates",
                removable=False,
            ),
            DeprecationEntry(
                kind="telemetry_field",
                target="workflow_decision.v1.legacy_output",
                replaced_by="core.consolidation.status",
                slice_id="slice-check-state",
                contract_boundary="versioned output contract only after deprecation window",
                removable=False,
            ),
        )
    )
