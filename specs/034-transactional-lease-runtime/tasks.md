# Tasks: Transactional Lease Runtime and Persistence Boundary

**Input**: `spec.md`, `plan.md`, `adr-001-persistence-boundary.md`,
`data-model.md`, and `contracts/transaction-boundary-v1.md`

## Phase 0 — Architecture and Governance Gate

- [x] T001 Verify GitHub default branch, current checkout, PR #285 merge target/
  commit, and Spec 033's bounded correctness claim.
- [x] T002 Inventory current session replacement, ledger append, lease entry points,
  and orchestrator shadow ownership.
- [x] T003 Complete Architecture Preflight and persistence option comparison.
- [x] T004 Select SQLite and reject file-lock/CAS, custom WAL, and daemon options.
- [x] T005 Define canonical entities, projections, transition/recovery tables, and
  artifact/telemetry boundaries.
- [x] T006 Apply the PR stacking dependency gate and define A -> B -> C ownership.
- [x] T007 Obtain review and approval for the Constitution Principle I amendment
  and persistence-boundary v1 contract.

**Checkpoint**: T007 blocks all implementation tasks. Do not create a compatibility
shim or dual-primary mode to proceed around it.

## Phase A — Atomic Store and Cross-Process Claim

**Owning branch**: `feat/034a-atomic-runtime-store`

- [x] A001 Amend Constitution Principle I with version rationale and review all
  dependent templates/guidance.
- [x] A002 Write failing executable schema, legacy migration, and projection
  authority contracts.
- [x] A003 Write failing multi-process same-item and overlapping-conflict races,
  bounded busy timeout, and stale-revision CAS tests.
- [x] A004 Implement the versioned SQLite store and transaction repository without
  network/artifact IO inside write transactions.
- [x] A005 Migrate lease/item/session/evidence state exactly once and preserve
  stable event identities; create and verify the immutable legacy-v1 recovery
  bundle before replacing compatibility projections.
- [x] A006 Route all lease transitions through the transaction API; return explicit
  `created`/`reentered` provenance and derive item claim projection.
- [x] A007 Materialize revision-stamped JSON/JSONL compatibility artifacts and
  prove external edits do not mutate truth.
- [x] A008 Add bounded privacy-safe transaction/migration OTel events and fail-open
  exporter tests.
- [x] A009 Update README, persistence contract documentation, and skill guidance
  only where public recovery/authority behavior changes.
- [x] A010 Run focused gates, then the complete repository Completion Standard.

## Phase B — Crash-Consistent Evidence, Outbox, and Recovery

**Owning branch**: `feat/034b-crash-consistent-outbox` (base A)

- [x] B001 Write child-process kill tests for every checkpoint in the transaction,
  outbox, and artifact materialization contracts.
- [x] B002 Route all remaining session/evidence mutation paths through A's
  repository and remove independent append/save production calls.
- [x] B003 Persist outbox plans with their state transition and record execution
  results in later transactions.
- [x] B004 Implement `in_flight -> unknown` restart recovery, external
  reconciliation, and effect-specific idempotent retry.
- [x] B005 Implement dirty projection tracking and deterministic rebuild without
  artifact-backed truth.
- [x] B006 Point final-gate and PR-session recovery at canonical state plus current
  GitHub facts.
- [x] B007 Add bounded recovery/outbox/materialization OTel events and privacy tests.
- [x] B008 Update versioned machine/status-to-action docs and tests for any exposed
  recovery reasons.
- [x] B009 Run focused crash/replay gates, complete repository gates, and affected
  PR-session final-gate with compact completion evidence.

## Phase C — Core/Shadow Lease Convergence

**Owning branch**: `feat/034c-orchestrator-lease-convergence` (base B)

- [ ] C001 Write failing contracts proving there is one lease authority and no
  independent shadow conflict/TTL/status/release policy.
- [ ] C002 Define/version the worker dispatch receipt if its serialized shape is
  public.
- [ ] C003 Replace shadow grant/release with volatile dispatch projection and
  canonical pre-action reconciliation.
- [ ] C004 Remove duplicate same-file conflict, TTL, terminal-state, and force-
  release logic plus obsolete rollback branches.
- [ ] C005 Add restart, stale dispatch, non-overlapping hunk, expiry, and release
  replay tests.
- [ ] C006 Add bounded privacy-safe orchestrator reconciliation OTel events.
- [ ] C007 Update orchestrator and packaged-skill guidance if the worker recovery
  action changes.
- [ ] C008 Run focused orchestrator gates, complete repository gates, and affected
  PR-session final-gate with compact completion evidence.

## Stack and Review Discipline

- Do not implement B on A's owning branch or C on B's owning branch.
- When a lower layer changes, repair it on that owning branch, cascade upward
  with authorized native Stack operations, and discard stale upper-layer evidence.
- Do not stage, commit, push, create/link Stack PRs, rebase, or merge without the
  corresponding explicit authorization.
