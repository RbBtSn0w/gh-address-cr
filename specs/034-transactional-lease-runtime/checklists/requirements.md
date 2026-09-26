# Requirements Checklist: Transactional Lease Runtime

**Purpose**: Architecture readiness and implementation-entry gate
**Created**: 2026-09-24
**Feature**: [spec.md](../spec.md)

## Architecture Closure

- [x] CHK001 Current branch, default branch, and PR #285 merge facts were verified.
- [x] CHK002 The authoritative owner, event inputs, canonical/projection shapes,
  policy tables, transaction boundary, outbox, artifact truth, telemetry boundary,
  recovery/replay, and orchestrator ownership are explicit.
- [x] CHK003 Cross-process claim, crash consistency, and shadow convergence share
  one transaction architecture rather than three local patches.
- [x] CHK004 Persistence candidates are compared against runtime fit, migration,
  concurrency, crash recovery, testability, compatibility, and complexity.
- [x] CHK005 SQLite is selected with rejected alternatives and consequences.
- [x] CHK006 A/B/C owning branches, material dependencies, contracts, OTel,
  verification, and completion criteria are defined.
- [x] CHK007 Artifact-backed truth, hidden fallback, extra ownership flags, and
  dual-primary writes are explicitly prohibited.

## Implementation Entry

- [x] CHK008 Constitution Principle I amendment is approved and landed.
- [x] CHK009 Persistence-boundary v1 and migration/downgrade semantics are approved.
- [x] CHK010 Phase A branch topology is authorized before code or native Stack
  mutations begin.

## Completion Evidence

- [x] CHK011 Each layer records focused failing-then-passing tests.
- [x] CHK012 Each layer completes install, lint, unit, CLI, agent manifest, and
  plugin payload gates.
- [x] CHK013 Affected PR-session layers complete final-gate and retain compact
  completion evidence with telemetry coverage and report artifacts.
- [x] CHK014 Every changed upper Stack layer is revalidated after lower-layer
  revision changes.

## Closure Evidence

- Constitution 2.2.0 and the persistence-boundary approval landed in PR #287.
- Phase A landed in PR #288, Phase B in PR #290, and Phase C in PR #292.
- Each implementation PR passed its focused and complete repository gates before
  merge; affected PR-session work retained compact `final-gate` evidence.
- The completed A -> B -> C Stack is now represented by its squash-merge commits
  on `develop`; no Phase D is required by this specification.
