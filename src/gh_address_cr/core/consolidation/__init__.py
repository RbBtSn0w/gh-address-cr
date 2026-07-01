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

__all__: list[str] = []
