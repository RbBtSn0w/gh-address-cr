---
description: "Task list for Evidence-Gated Runtime Consolidation"
---

# Tasks: Evidence-Gated Runtime Consolidation

**Input**: Design documents from `specs/024-runtime-consolidation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/README.md

**Tests**: Required. This feature changes runtime-kernel authority, adds CLI
surface, and adds versioned artifacts. Per the constitution, runtime-kernel and
public-contract changes MUST ship replay/contract tests. Tests are written FIRST
(TDD) and MUST fail before implementation.

**Organization**: Grouped by user story. US1 (Authority + Parity) is the MVP and
must land before US2/US3, which build the reversible rollout and evidence gates
on top of it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: US1 / US2 / US3 for user-story phases; none for Setup/Foundational/Polish
- Exact repo-root file paths per plan.md structure (`src/gh_address_cr/...`, `tests/...`)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the consolidation package and test scaffolding.

- [x] T001 Create `src/gh_address_cr/core/consolidation/__init__.py` exporting the public entities (empty re-export stub) per plan structure; git commit -m "chore: init consolidation package"
- [x] T002 [P] Create `tests/consolidation/__init__.py` and an empty `tests/consolidation/fixtures/` directory for replay fact sets; git commit -m "chore: setup test directory structures"
- [x] T003 [P] Add a supported-cohort replay fixture for the `check` axis — review-thread + check-state facts from which `slice-check-state` derives PR check state — in `tests/consolidation/fixtures/check_state_facts.json`; git commit -m "test: add check state fact replay fixture"

**Checkpoint**: Package and test locations exist; `ruff`/`mypy` already configured at repo root.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared types, reason codes, and schema-version constants that every
story depends on. No user story work may begin until this phase is complete.

**⚠️ CRITICAL**: Complete before Phase 3.

- [x] T004 Define shared enums (`StateAxis` incl. `local_finding`, `Owner`, `CompatibilityDirection`, `RolloutStage`) and schema-version constants (`authority-map.v1`, `parity-report.v1`, `rollout-state.v1`, `deprecation-inventory.v1`) in `src/gh_address_cr/core/consolidation/types.py`; git commit -m "chore: define shared consolidation types and constants"
- [x] T005 [P] Add consolidation reason codes (`DUPLICATE_STATE_OWNER`, `UNKNOWN_SLICE`, `INSUFFICIENT_EVIDENCE`, `PARITY_DIFF`, `QUALITY_REGRESSION`, `DEPRECATION_WINDOW_OPEN`) to `src/gh_address_cr/core/protocol_codes.py`; git commit -m "chore: add consolidation protocol reason codes"
- [x] T006 Document the Architecture Preflight owners for the pilot `slice-check-state` (facts, projection, policy, side-effect boundary, recovery) as a docstring/module header in `src/gh_address_cr/core/consolidation/__init__.py`; git commit -m "docs: document pilot slice preflight owners in module docstring"

**Checkpoint**: Shared vocabulary ready — stories can proceed.

---

## Phase 3: User Story 1 - Declare One Authority Per Runtime State Axis (Priority: P1) 🎯 MVP

**Goal**: One authoritative owner per state axis with a side-effect-free parity
proof that legacy and candidate paths agree, surfaced via `consolidation status`
and `consolidation parity`.

**Independent Test**: Run `consolidation status --json` (exactly one owner per
axis; duplicate fixture fails loud) and `consolidation parity --slice
slice-check-state --json` (matching projection/decision/command-plan, zero side
effects, deterministic across runs).

### Tests for User Story 1 (write first, must fail)

- [x] T007 [P] [US1] Contract test: `RuntimeAuthorityMap` accepts exactly one owner per axis and raises fail-loud `DUPLICATE_STATE_OWNER` on a duplicate-owner fixture, in `tests/consolidation/test_authority_map.py`; git commit -m "test: assert duplicate state owner fails loud"
- [x] T008 [P] [US1] Contract test: every axis is present during partial migration (FR-019) in `tests/consolidation/test_authority_map.py`; git commit -m "test: assert all axes present during partial migration"
- [x] T009 [P] [US1] Replay test: `ParityObserver` produces a deterministic `parity-report.v1` for the same `fact_digest` with `side_effects_executed == 0`, in `tests/consolidation/test_parity_observation.py`; git commit -m "test: assert parity observer is deterministic and side-effect free"
- [x] T010 [P] [US1] Replay test: parity compares projection, policy decision, and planned-command digests; an injected candidate divergence populates `differences`, in `tests/consolidation/test_parity_observation.py`; git commit -m "test: assert candidate divergence is reported in parity differences"
- [x] T011 [P] [US1] Guard test: parity observation performs zero GitHub calls (inject a client that raises on any call) in `tests/consolidation/test_parity_observation.py`; git commit -m "test: assert parity observation performs zero GitHub calls"
- [x] T012 [P] [US1] CLI contract test: `consolidation status --json` emits `authority-map.v1`; unknown axis/duplicate exits non-zero, in `tests/contract/test_consolidation_cli.py`; git commit -m "test: verify consolidation status CLI schema and errors"
- [x] T013 [P] [US1] CLI contract test: `consolidation parity --slice <id> --json` emits `parity-report.v1`; unknown slice exits non-zero with `UNKNOWN_SLICE`, in `tests/contract/test_consolidation_cli.py`; git commit -m "test: verify consolidation parity CLI schema and errors"
- [x] T014 [P] [US1] Public-contract non-regression test (FR-009 / SC-009): registering the `consolidation` command group does not drift existing `review` / `threads` / `agent` machine summaries, reason codes, wait states, or exit codes, in `tests/contract/test_public_contract_stability.py`; git commit -m "test: assert cli group registration does not drift existing commands"

### Implementation for User Story 1

- [x] T015 [US1] Implement `RuntimeAuthorityMap` dataclass with per-axis validation and `to_dict()`/`authority-map.v1` serialization in `src/gh_address_cr/core/consolidation/authority_map.py`; git commit -m "feat: implement RuntimeAuthorityMap with axis validation"
- [x] T016 [US1] Implement the `AuthorityMap` projection (derive owners for the active runtime, fail loud on duplicate/ambiguous ownership) in `src/gh_address_cr/core/consolidation/authority_map.py`; git commit -m "feat: implement AuthorityMap projection with duplicate owner detection"
- [x] T017 [US1] Implement `ParityObservation` dataclass and `parity-report.v1` serialization in `src/gh_address_cr/core/consolidation/parity.py`; git commit -m "feat: implement ParityObservation schema serialization"
- [x] T018 [US1] Implement `ParityObserver.observe(slice_id, facts)` replaying facts through the legacy projection and a registered pluggable candidate-projection hook (the pilot registers a synthetic candidate; the real check-axis kernel projection is deferred to the slice's own migration), comparing projection/decision using `runtime_kernel` projections+policies, in `src/gh_address_cr/core/consolidation/parity.py`; git commit -m "feat: implement ParityObserver fact replay execution"
- [x] T019 [US1] Extend `ParityObserver` to compare planned commands by idempotency key + `planned_command_digest` without executing them in `src/gh_address_cr/core/consolidation/parity.py`; git commit -m "feat: extend ParityObserver to compare planned command digests"
- [ ] T020 [US1] Create `src/gh_address_cr/commands/consolidation.py` with a `status` subcommand rendering the authority map (text + `--json`); git commit -m "feat: implement status command in consolidation CLI"
- [ ] T021 [US1] Add a `parity` subcommand (`--slice`, `--json`) to `src/gh_address_cr/commands/consolidation.py`; git commit -m "feat: implement parity command in consolidation CLI"
- [ ] T022 [US1] Register the advanced `consolidation` command group in `src/gh_address_cr/cli.py` (additive; does not alter `review` default path); git commit -m "feat: register consolidation command group in main CLI"

**Checkpoint**: US1 fully functional and independently testable — authority is single-owned and parity is provable offline.

---

## Phase 4: User Story 2 - Migrate Through Reversible Slices (Priority: P1)

**Goal**: Bounded, reversible migration slices governed by a deterministic
rollout gate; any enabled slice can be disabled without rewriting runtime facts.
Duplicate-ownership deprecation proceeds only through an explicit inventory.

**Independent Test**: Promote `slice-check-state` shadow→opt_in (provisional
evidence ok), attempt opt_in→default without durable evidence (blocked), then
roll back and assert `session.json`/`evidence.jsonl` are unchanged.

### Tests for User Story 2 (write first, must fail)

- [ ] T023 [P] [US2] Contract test: a `MigrationSlice` missing facts/projection/policy/side-effect boundary/replay coverage/cohort/rollback cannot advance past `shadow`, in `tests/consolidation/test_migration_slice.py`; git commit -m "test: assert incomplete migration slice cannot advance past shadow"
- [ ] T024 [P] [US2] Contract test: a candidate that writes a side effect during projection/policy evaluation fails the slice contract, in `tests/consolidation/test_migration_slice.py`; git commit -m "test: assert side effects during shadow evaluation fail slice contract"
- [ ] T025 [P] [US2] Test (SC-006): an unsupported PR cohort routes to the legacy/supported path (axis reports `legacy` authority) during partial migration, in `tests/consolidation/test_migration_slice.py`; git commit -m "test: assert unsupported PR cohort routes to legacy path"
- [ ] T026 [P] [US2] Test (FR-020 / SC-010): a slice that adds a state axis without removing a duplicate owner (no state-space reduction) is rejected, in `tests/consolidation/test_migration_slice.py`; git commit -m "test: reject slice that adds axis without duplicate owner removal"
- [ ] T027 [P] [US2] Contract test: `rollout-state.v1` round-trips through atomic load/validate/write and rejects malformed stage values, in `tests/consolidation/test_rollout_state.py`; git commit -m "test: verify rollout-state.v1 atomic read/write and validation"
- [ ] T028 [P] [US2] Gate test: `RolloutPolicy` allows shadow→opt_in on provisional evidence but blocks opt_in→default with `INSUFFICIENT_EVIDENCE`, in `tests/consolidation/test_rollout_gate.py`; git commit -m "test: assert RolloutPolicy forward transition gates"
- [ ] T029 [P] [US2] Gate test: an unexplained parity difference blocks default with `PARITY_DIFF`; `deleted` requires `deprecation_window_complete == true`, in `tests/consolidation/test_rollout_gate.py`; git commit -m "test: assert parity diff blocks default and deleted requires deprecation complete"
- [ ] T030 [P] [US2] Rollback test: breaching a `RollbackTrigger` reverts stage and leaves runtime facts/execution evidence byte-for-byte unchanged, in `tests/consolidation/test_rollback.py`; git commit -m "test: assert rollback trigger breach reverts stage without fact rewrite"
- [ ] T031 [P] [US2] Contract test (FR-017): `deprecation-inventory.v1` enumerates duplicate models/shims/telemetry fields with a documented contract boundary and rejects deletion entries whose slice is below `deprecating`, in `tests/consolidation/test_deprecations.py`; git commit -m "test: verify deprecation-inventory.v1 schema and deletion constraints"
- [ ] T032 [P] [US2] CLI contract test: `consolidation rollout --slice <id> --to <stage>` returns reason code + non-zero on a blocked transition, in `tests/contract/test_consolidation_cli.py`; git commit -m "test: verify consolidation rollout CLI blocked transition behaviors"

### Implementation for User Story 2

- [ ] T033 [US2] Implement `MigrationSlice` dataclass and completeness/acceptance-gate validation in `src/gh_address_cr/core/consolidation/migration_slice.py`; git commit -m "feat: implement MigrationSlice data model and validation"
- [ ] T034 [US2] Add state-space-reduction validation to `MigrationSlice` (reject a slice that adds an axis without removing a duplicate owner) in `src/gh_address_cr/core/consolidation/migration_slice.py`; git commit -m "feat: implement state-space reduction check on MigrationSlice"
- [ ] T035 [US2] Implement `rollout-state.v1` load/validate/atomic-write in `src/gh_address_cr/core/consolidation/rollout_state.py`; git commit -m "feat: implement atomic load/write for rollout-state.v1"
- [ ] T036 [US2] Implement `RollbackTrigger` dataclass (dimension, threshold, reversal_stage) in `src/gh_address_cr/core/consolidation/rollout.py`; git commit -m "feat: implement RollbackTrigger model mapping"
- [ ] T037 [US2] Implement `RolloutPolicy` forward-transition function (gate holds → next stage; else reason code) and rollback path (trigger breach → reversal stage via rollout-state transition only) in `src/gh_address_cr/core/consolidation/rollout.py`; git commit -m "feat: implement RolloutPolicy forward and backward rules"
- [ ] T038 [US2] Register the pilot `slice-check-state` definition (axes=[check], synthetic candidate-projection hook + fixture cohort, parity + rollback triggers; real check-axis kernel projection deferred to the slice's own future migration) in `src/gh_address_cr/core/consolidation/migration_slice.py`; git commit -m "feat: register pilot slice-check-state definition"
- [ ] T039 [US2] Implement `deprecation-inventory.v1` (duplicate models, compatibility shims, telemetry fields + documented contract boundary) and a `consolidation deprecations --json` subcommand in `src/gh_address_cr/core/consolidation/deprecations.py` (FR-017); git commit -m "feat: implement deprecation-inventory.v1 schema and CLI query"
- [ ] T040 [US2] Add a `rollout` subcommand (`--slice`, `--to`, `--json`) to `src/gh_address_cr/commands/consolidation.py` wiring `RolloutPolicy` + `rollout_state`; git commit -m "feat: implement rollout command in consolidation CLI"

**Checkpoint**: US2 delivers a reversible slice lifecycle and an explicit deprecation inventory proven by the pilot slice.

---

## Phase 5: User Story 3 - Accept Optimizations Only With Evaluation Evidence (Priority: P2)

**Goal**: The three optimization hypotheses are registered, gated independently
by feature-023 evidence, and keep safe fallbacks; evaluation output never becomes
runtime truth.

**Independent Test**: Register the three hypotheses; confirm each stage changes
independently, `INSUFFICIENT_EVIDENCE`/quality regression keeps a hypothesis
non-default, `--full` output remains default, and a non-session review path still
completes.

### Tests for User Story 3 (write first, must fail)

- [ ] T041 [P] [US3] Test: the three `OptimizationHypothesis` entries accept/reject/roll back independently in `rollout-state.v1`, in `tests/consolidation/test_optimization_hypotheses.py`; git commit -m "test: assert three optimization hypotheses can opt-in and rollback independently"
- [ ] T042 [P] [US3] Test (FR-013): feature-023 `evaluation.v1` results are consumed read-only as rollout evidence and never written into `session.json`/evidence ledger, and evaluation refs never appear in `final-gate` evidence inputs, in `tests/consolidation/test_evidence_consumption.py`; git commit -m "test: assert evaluation results are read-only and never affect runtime truth"
- [ ] T042b [P] [US3] Fail-open test: verify that when feature 023 evaluation is missing or returns errors, core review orchestration still executes successfully (fail-open) and does not block review completion, in `tests/consolidation/test_evidence_consumption.py`; git commit -m "test: assert core review flow is fail-open when evaluation evidence is missing"
- [ ] T043 [P] [US3] Test: `INSUFFICIENT_EVIDENCE`, unknown durable outcome, or regressed guardrail blocks default rollout and legacy deletion, in `tests/consolidation/test_evidence_consumption.py`; git commit -m "test: assert insufficient evidence blocks default optimization rollout"
- [ ] T044 [P] [US3] Test: `output_truncation` is not default and `--full` returns untruncated output until its gate passes, in `tests/consolidation/test_optimization_hypotheses.py`; git commit -m "test: assert output_truncation remains non-default until gate passes"
- [ ] T044b [P] [US3] CLI contract test: verify that `consolidation status --json` includes the active hypothesis states when optimization hypotheses are registered, in `tests/contract/test_consolidation_cli.py`; git commit -m "test: verify consolidation status CLI includes active hypothesis states"
- [ ] T045 [P] [US3] Test: the non-session execution path remains available while `command_session` is below its gate, in `tests/consolidation/test_optimization_hypotheses.py`; git commit -m "test: assert non-session path remains available while command_session is below default"

### Implementation for User Story 3

- [ ] T046 [US3] Implement `OptimizationHypothesis` dataclass (guardrails, cohort, staged enablement, stop condition, rollback action, safe fallback) in `src/gh_address_cr/core/consolidation/optimization.py`; git commit -m "feat: implement OptimizationHypothesis data model and fallbacks"
- [ ] T047 [US3] Add the `hypotheses` section to `rollout-state.v1` load/validate in `src/gh_address_cr/core/consolidation/rollout_state.py`; git commit -m "feat: add hypotheses registry to rollout-state.v1 schema"
- [ ] T048 [US3] Implement read-only feature-023 evidence adapter (map `evaluation.v1` comparison result → rollout evidence / `INSUFFICIENT_EVIDENCE`) in `src/gh_address_cr/core/consolidation/evidence.py`; git commit -m "feat: implement read-only evaluation.v1 evidence adapter"
- [ ] T049 [US3] Wire the evidence adapter into `RolloutPolicy` so durable feature-023 evidence is required for `default`/`deleted` in `src/gh_address_cr/core/consolidation/rollout.py`; git commit -m "feat: wire evaluation evidence adapter into RolloutPolicy"
- [ ] T050 [US3] Register the three hypotheses (`output_truncation`, `command_session`, `workflow_surface_removal`) with safe fallbacks in `src/gh_address_cr/core/consolidation/optimization.py`; git commit -m "feat: register three optimization hypotheses with safe fallbacks"
- [ ] T051 [US3] Surface hypothesis state in `consolidation status` output in `src/gh_address_cr/commands/consolidation.py`; git commit -m "feat: surface hypothesis state in consolidation status output"

**Checkpoint**: US3 gates each optimization independently on real evidence with safe fallbacks intact.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T052 Update `skill/` Status-to-Action guidance/diagnostics in `skill/references/status-action-map.md` to reference the advanced `consolidation` family (Behavioral Policy Layer only, no business logic); git commit -m "docs: update skill Status-to-Action diagnostics reference"
- [ ] T053 Add a repo-root doc note describing the reversible-migration workflow, the deprecation inventory, and the three optimization hypotheses in `docs/cli-reference.md`; git commit -m "docs: add reversible migration guide to cli reference doc"
- [ ] T054 Validate `quickstart.md` scenarios 1–6 end-to-end against the implemented CLI; git commit -m "test: validate quickstart scenarios end-to-end against CLI"
- [ ] T055 Run the full verification suite: `pip install -e .`, `ruff check src tests`, `python3 -m unittest discover -s tests`, `python3 -m gh_address_cr --help`, `python3 -m gh_address_cr consolidation status --json`, and confirm the `mypy` strict ratchet does not regress; git commit -m "chore: execute full verification suite and check mypy constraints"
- [ ] T056 [P] Performance-budget assertion (plan Performance Goals): a test asserting parity replay for the supported fixture stays within the ≤250 ms normal-path budget and slice-enablement lookup is O(number of slices), in `tests/consolidation/test_performance_budget.py`; git commit -m "test: assert parity replay performance remains within budget"

---

## Dependencies & Story Completion Order

- **Setup (P1) → Foundational (P2)**: strictly sequential; both block all stories.
- **US1 (P1, MVP)**: depends only on Foundational. Delivers authority + parity.
- **US2 (P1)**: depends on US1 (uses parity evidence in the rollout gate).
- **US3 (P2)**: depends on US2 (extends `RolloutPolicy` + `rollout-state`).
- **Polish**: after US1–US3.

```text
Setup → Foundational → US1 → US2 → US3 → Polish
```

## Parallel Execution Opportunities

- **Setup**: T002, T003 in parallel after T001.
- **Foundational**: T005 parallel with T004; T006 after T004.
- **US1 tests**: T007–T014 all `[P]` (independent files/cases) before implementation T015–T022.
- **US2 tests**: T023–T032 all `[P]` before implementation T033–T040.
- **US3 tests**: T041–T045 all `[P]` before implementation T046–T051.
- **Polish**: T052, T053, T056 in parallel; T054 then T055 last.

## Implementation Strategy

- **MVP = US1**: single-owned authority + offline parity proof is independently
  shippable and de-risks everything downstream.
- **Increment 2 = US2**: reversible slice lifecycle + explicit deprecation
  inventory proven by the `slice-check-state` pilot (no public-contract change —
  parity is the dominant risk).
- **Increment 3 = US3**: evidence-gated optimization hypotheses with safe
  fallbacks; no legacy deletion on provisional evidence alone.
- Actual deletion of `workflow_matching.py` / imperative `workflow.py` branches
  is explicitly **out of scope** for this feature (see spec FR-018 deferral) and
  only follows once all slices reach `default` and complete their deprecation
  windows.
