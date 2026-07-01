"""Shared vocabulary for the runtime-consolidation framework (feature 024).

Enums and schema-version constants used across the authority map, parity
observer, migration slices, rollout gate, and deprecation inventory. Kept
dependency-free so every consolidation module can import it without cycles.
"""

from __future__ import annotations

from enum import Enum


class StateAxis(str, Enum):
    """A runtime state axis that a migration slice can transfer ownership of.

    Mirrors the enumeration in spec FR-001. Exactly one authority owns each axis
    at a time; any compatibility output is explicitly derived.
    """

    REVIEW_ITEM = "review_item"
    LEASE = "lease"
    CHECK = "check"
    LOCAL_FINDING = "local_finding"
    SIDE_EFFECT_EVIDENCE = "side_effect_evidence"
    TELEMETRY_EVIDENCE = "telemetry_evidence"
    FINAL_GATE_ELIGIBILITY = "final_gate_eligibility"


class Owner(str, Enum):
    """The authoritative owner of a state axis."""

    LEGACY = "legacy"
    KERNEL = "kernel"


class CompatibilityDirection(str, Enum):
    """Which direction a derived compatibility projection flows.

    ``NONE`` is only valid when a single path exists for the axis (no migration
    in flight).
    """

    LEGACY_FROM_KERNEL = "legacy_from_kernel"
    KERNEL_FROM_LEGACY = "kernel_from_legacy"
    NONE = "none"


class RolloutStage(str, Enum):
    """Deterministic rollout stages for a slice or optimization hypothesis.

    Stages advance monotonically except on rollback. Provisional evidence may
    unlock ``SHADOW``/``OPT_IN``; ``DEFAULT`` requires durable feature-023
    evidence; ``DELETED`` additionally requires a completed deprecation window.
    """

    SHADOW = "shadow"
    OPT_IN = "opt_in"
    DEFAULT = "default"
    DEPRECATING = "deprecating"
    DELETED = "deleted"


# Ordered forward progression. Rollback moves to an earlier supported stage.
ROLLOUT_STAGE_ORDER: tuple[RolloutStage, ...] = (
    RolloutStage.SHADOW,
    RolloutStage.OPT_IN,
    RolloutStage.DEFAULT,
    RolloutStage.DEPRECATING,
    RolloutStage.DELETED,
)

# Versioned artifact schema identifiers (public contract surface).
AUTHORITY_MAP_SCHEMA = "authority-map.v1"
PARITY_REPORT_SCHEMA = "parity-report.v1"
ROLLOUT_STATE_SCHEMA = "rollout-state.v1"
DEPRECATION_INVENTORY_SCHEMA = "deprecation-inventory.v1"
