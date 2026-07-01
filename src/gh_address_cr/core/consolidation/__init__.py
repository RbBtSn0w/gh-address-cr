"""Reversible runtime-consolidation framework (feature 024).

Public entities are re-exported here as they are implemented. The framework
provides a Runtime Authority Map (one owner per state axis), a side-effect-free
parity observer, migration-slice contracts, and a deterministic rollout gate so
that legacy paths migrate onto the event-sourced ``runtime_kernel`` in bounded,
reversible slices governed by feature-023 evidence.

Architecture Preflight — pilot ``slice-check-state`` (Constitution Principle IX):

- Authoritative owner: today the legacy path owns the ``check`` axis; the slice
  registers a candidate owner behind the rollout gate. The real check-axis kernel
  projection is deferred to the slice's own future migration; this framework only
  proves the reversible comparison machinery.
- External facts / event inputs: ``review_thread_observed`` and
  ``check_run_observed`` runtime facts (see ``runtime_kernel.events``); replayed
  from archived/synthetic fixtures, never re-fetched during parity.
- Projection: legacy projection vs a registered pluggable candidate-projection
  hook. Parity compares projections, policy decisions, and planned commands only.
- Policy: existing ``runtime_kernel.policies.evaluate_review_policy`` over each
  projection; the slice adds no new status conditionals.
- Side-effect boundary: parity observation is read-only and executes zero
  GitHub commands; it compares *planned* commands by idempotency key + digest.
- Recovery / rollback: disabling the slice is a single ``rollout-state.v1``
  transition; runtime facts and execution evidence are never rewritten, and no
  reporting artifact is treated as truth.
"""

from __future__ import annotations

from gh_address_cr.core.consolidation.authority_map import AuthorityEntry, RuntimeAuthorityMap, derive_authority_map
from gh_address_cr.core.consolidation.deprecations import DeprecationEntry, DeprecationInventory
from gh_address_cr.core.consolidation.evidence import (
    RolloutEvidence,
    RolloutEvidenceStatus,
    evaluation_to_rollout_evidence,
)
from gh_address_cr.core.consolidation.migration_slice import (
    MigrationSlice,
    RollbackTrigger,
    get_registered_slice,
    registered_slices,
)
from gh_address_cr.core.consolidation.optimization import (
    HypothesisState,
    OptimizationHypothesis,
    default_hypothesis_states,
    default_optimization_hypotheses,
)
from gh_address_cr.core.consolidation.rollout import RolloutDecision, RolloutPolicy
from gh_address_cr.core.consolidation.rollout_state import RolloutSliceState, RolloutState
from gh_address_cr.core.consolidation.types import (
    AUTHORITY_MAP_SCHEMA,
    DEPRECATION_INVENTORY_SCHEMA,
    PARITY_REPORT_SCHEMA,
    ROLLOUT_STATE_SCHEMA,
    CompatibilityDirection,
    ConsolidationError,
    Owner,
    RolloutStage,
    StateAxis,
)

__all__ = [
    "AUTHORITY_MAP_SCHEMA",
    "AuthorityEntry",
    "CompatibilityDirection",
    "ConsolidationError",
    "DEPRECATION_INVENTORY_SCHEMA",
    "DeprecationEntry",
    "DeprecationInventory",
    "HypothesisState",
    "MigrationSlice",
    "Owner",
    "OptimizationHypothesis",
    "PARITY_REPORT_SCHEMA",
    "RolloutDecision",
    "RolloutEvidence",
    "RolloutEvidenceStatus",
    "RolloutPolicy",
    "RolloutSliceState",
    "RolloutStage",
    "RolloutState",
    "ROLLOUT_STATE_SCHEMA",
    "RollbackTrigger",
    "RuntimeAuthorityMap",
    "StateAxis",
    "default_hypothesis_states",
    "default_optimization_hypotheses",
    "derive_authority_map",
    "evaluation_to_rollout_evidence",
    "get_registered_slice",
    "registered_slices",
]
