# Tasks: O(changed) Runtime Transaction Hot Path

## Phase 0 — Evidence and Contracts

- [x] T001 Reproduce the M-profile degradation on current `develop`.
- [x] T002 Record Architecture Preflight and implementation design.
- [x] T003 Add a RED contract proving bounded transactions do not normalize the whole session graph.
- [x] T004 Add a RED contract proving unchanged items and leases are not re-encoded.
- [x] T005 Add characterization for one snapshot load per transaction.

## Phase 1 — Bounded Transaction

- [x] T006 Add the bounded transaction abstraction selected by the revised preflight.
- [x] T007 Retain canonical session/item/lease fragments required by that abstraction.
- [x] T008 Normalize and write only changed entities on the bounded path.
- [x] T009 Keep `replace()` on the explicit full fallback.

## Phase 2 — Projection

- [x] T010 Assemble compact `session.json` from canonical fragments.
- [x] T011 Add randomized mutation equivalence across session/item/lease add, update, and delete.
- [x] T012 Preserve crash recovery, drift repair, and concurrent materialization behavior.

## Historical Architecture Checkpoint — reverted prototype

- [x] T018 Benchmark the reverted prototype and compare it with SC-001.
- [x] T019 Stop after SC-001 remains red and record the corrected cost model.
- [x] T020 Add a RED contract proving a targeted command does not decode unrelated item payloads.
- [x] T021 Design a bounded canonical working set without dict-proxy emulation.
- [x] T022 Measure the full-projection atomic-write floor independently of entity decoding.
- [x] T023 Re-profile the full workflow and identify retained terminal leases as the remaining growth axis.
- [x] T024 Add a RED contract proving active-lease policy does not decode terminal lease payloads.
- [x] T025 Define the smallest versioned command working-set contract backed by normalized SQLite columns.
- [x] T026 Prove list/recovery surfaces still materialize complete terminal lease history.
- [x] T027 Rerun M before widening the lease view to any additional command path.

## Phase 1B — Corrected Cost Attribution and Event Normalization

- [x] T028 Add per-stage load/transaction/materialization benchmark attribution.
- [x] T029 Move explicit claim and normal submit preflight to bounded reads.
- [x] T030 Add RED migration/replay contracts for normalized lease events.
- [x] T031 Implement runtime schema v3 and atomic v2-to-v3 migration.
- [x] T032 Append new lease events without rewriting the session root.
- [x] T033 Reassemble full loads and compatibility projections byte-identically.
- [x] T034 Rerun M and stop if transaction degradation remains above the budget.
- [x] T035 Measure L and prove full session projection is the remaining growth boundary.
- [x] T036 Add RED dirty/current artifact-cadence contracts.
- [x] T037 Keep incremental evidence current while deferring `session.json`.
- [x] T038 Prove full-load/recovery materializes the latest revision byte-identically.
- [x] T039 Rerun M/L and tracing gates under the versioned schema-v3 contract.

## Phase 3 — Performance and Closeout

- [x] T013 Run focused contract tests and surrounding runtime-store suites.
- [x] T014 Run M and L plain benchmarks and record results.
- [x] T015 Run alternating traced/plain benchmarks and record p50/p90 overhead.
- [x] T016 Run repository lint, mypy, unit, CLI, agent-manifest, and plugin-payload gates.
- [x] T017 Record validation evidence and draft Conventional Commit message.

## Phase 4 — Review Closure

- [x] T040 Materialize canonical state before `submit-feedback` reads session context.
- [x] T041 Emit bounded persistence telemetry for busy, failed, and invariant-violation exits.
- [x] T042 Add a RED contract and reject writes to unselected pre-existing identities.
- [x] T043 Record ADR-002 and align the specification with the enforced write-scope contract.
- [x] T044 Route the public explicit materialization boundary through canonical row fragments.
