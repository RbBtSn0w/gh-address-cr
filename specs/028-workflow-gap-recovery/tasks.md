# Tasks: Workflow Gap Recovery

**Input**: Design documents from `/specs/028-workflow-gap-recovery/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Include test tasks for every changed runtime behavior, CLI contract, status-to-action mapping change, final-gate outcome, telemetry guidance rule, GitHub preflight diagnostic, and packaged-skill contract updated by this feature.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no unmet dependencies)
- **[Story]**: Which user story this task belongs to (e.g. `[US1]`, `[US2]`, `[US3]`)
- Every task includes exact file path(s)

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the shared fixture and contract scaffolding this feature will build on

- [X] T001 Create workflow-gap regression fixture set in `tests/fixtures/session_engine/workflow_gap_recovery.json`
- [X] T002 [P] Create recovery-surface contract test scaffold in `tests/contract/test_workflow_gap_recovery_contract.py`
- [X] T003 [P] Create runtime/docs sync regression scaffold in `tests/test_workflow_gap_recovery_docs.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish shared recovery classification and contract boundaries before user-story work begins

**⚠️ CRITICAL**: No user story work should begin until this phase is complete

- [X] T004 Define shared terminal-item recovery classification helpers in `src/gh_address_cr/core/runtime_kernel/final_gate.py`
- [X] T005 [P] Add gate-level next-action routing helpers for publish-vs-reconcile decisions in `src/gh_address_cr/core/gate.py`
- [X] T006 [P] Add reusable recovery-surface fixture helpers in `tests/helpers.py`
- [X] T007 Extend recovery-surface contract assertions for machine summaries and command templates in `tests/contract/test_workflow_gap_recovery_contract.py`

**Checkpoint**: Shared recovery vocabulary, fixtures, and gate-routing seams are ready

---

## Phase 3: User Story 1 - Recover blocked final-gate sessions (Priority: P1) 🎯 MVP

**Goal**: Make `final-gate` route terminal GitHub-thread evidence gaps to supported recovery paths instead of dead-end loops

**Independent Test**: Reproduce closed-thread reply/validation evidence gaps and confirm `final-gate` points to reconcile-or-publish correctly without requiring manual artifact edits

### Tests for User Story 1

- [X] T008 [P] [US1] Add final-gate regression coverage for reconcile-only blockers in `tests/test_final_gate.py`
- [X] T009 [P] [US1] Add closed-thread validation reconcile coverage in `tests/test_resolved_thread_validation_gap.py`
- [X] T010 [P] [US1] Add mixed-claimability matching regression for terminal threads in `tests/test_control_plane_fix_all_workflow.py`
- [X] T011 [P] [US1] Add final-gate regression coverage for explicit non-blocking historical-item classification in `tests/test_final_gate.py`

### Implementation for User Story 1

- [X] T012 [US1] Extend final-gate fact/projection data for terminal historical blockers in `src/gh_address_cr/core/runtime_kernel/final_gate.py`
- [X] T013 [US1] Implement publish-vs-reconcile next-action routing and explicit non-blocking historical classification in `src/gh_address_cr/core/gate.py`
- [X] T014 [US1] Define or refine machine-readable recovery reason codes and summary fields for historical-item outcomes in `src/gh_address_cr/core/protocol_codes.py`, `src/gh_address_cr/core/models.py`, and `src/gh_address_cr/commands/final_gate.py`
- [X] T015 [US1] Refine terminal reply-evidence reconcile payloads and session mutations in `src/gh_address_cr/core/workflow.py`
- [X] T016 [US1] Refine terminal validation-evidence reconcile payloads and guards in `src/gh_address_cr/core/workflow.py`
- [X] T017 [US1] Align recovery-surface guidance with terminal reconcile and non-blocking historical behavior in `skill/references/status-action-map.md` and `skill/SKILL.md`

**Checkpoint**: `final-gate` can distinguish claimable publish paths from terminal reconcile paths and remains independently testable

---

## Phase 4: User Story 2 - Unblock item handling after lease or claim conflicts (Priority: P2)

**Goal**: Surface active lease ownership and deterministic recovery guidance when batch claims block later item-by-item handling

**Independent Test**: Reproduce batch-claimed or active-lease conflicts and confirm the runtime reports lease-owned blockers with safe recovery actions instead of only `NO_ELIGIBLE_ITEM`

### Tests for User Story 2

- [X] T018 [P] [US2] Add lease-owned blocker regression coverage in `tests/test_issue142_stale_lease_deadlock.py`
- [X] T019 [P] [US2] Add resolve-mode and item-targeting contract coverage in `tests/test_agent_resolve_guards.py`
- [X] T020 [P] [US2] Add no-match-vs-lease-locked routing coverage in `tests/test_control_plane_fix_all_workflow.py`

### Implementation for User Story 2

- [X] T021 [US2] Expose lease-recovery details on list/recovery projections in `src/gh_address_cr/core/leases.py`
- [X] T022 [US2] Distinguish true no-match from lease-blocked matches in `src/gh_address_cr/core/workflow_matching.py`
- [X] T023 [US2] Return lease-owned blocker diagnostics from agent resolve flows in `src/gh_address_cr/commands/agent.py`
- [X] T024 [US2] Update lease-aware status-to-action guidance in `skill/references/status-action-map.md`
- [X] T025 [US2] Add packaged-skill recovery examples for lease-owned items in `skill/SKILL.md`

**Checkpoint**: Lease-blocked work reports authoritative ownership and recovery guidance without weakening lease protections

---

## Phase 5: User Story 3 - Treat environment-specific diagnostics honestly (Priority: P3)

**Goal**: Reclassify local telemetry and wrapped GitHub permission failures so expected local conditions are advisory and true blockers remain explicit

**Independent Test**: Reproduce local `runtime-only` runs and wrapped-`gh` permission failures, then verify the runtime distinguishes advisory coverage from blocking telemetry defects and permission mismatch from generic environment failure

### Tests for User Story 3

- [X] T026 [P] [US3] Add runtime-only advisory guidance regression coverage in `tests/test_final_gate.py`
- [X] T027 [P] [US3] Add completion-summary and wrapper diagnostic coverage in `tests/test_python_wrappers.py`
- [X] T028 [P] [US3] Add GitHub preflight diagnostic classification coverage in `tests/test_native_foundation.py` and `tests/test_runtime_packaging.py`
- [X] T029 [P] [US3] Add environment-diagnostic payload-shape coverage for `severity`, `reason_code`, and `source_scope` in `tests/test_python_wrappers.py` and `tests/test_native_foundation.py`

### Implementation for User Story 3

- [X] T030 [US3] Reclassify local runtime-only attention-item guidance in `src/gh_address_cr/commands/final_gate.py`
- [X] T031 [US3] Keep telemetry coverage labels stable while refining advisory semantics in `src/gh_address_cr/core/telemetry_reporting.py`
- [X] T032 [US3] Add wrapped-`gh` permission-mismatch diagnostics in `src/gh_address_cr/github/diagnostics.py` and `src/gh_address_cr/cli.py`
- [X] T033 [US3] Align telemetry and GitHub environment guidance in `skill/references/completion-contract.md`, `skill/references/status-action-map.md`, and `skill/SKILL.md`

**Checkpoint**: Local telemetry and wrapped GitHub permission failures are reported with honest severity and actionable next steps

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verify end-to-end contract consistency across runtime, docs, and packaging

- [X] T034 [P] Update feature notes and validation pointers in `specs/028-workflow-gap-recovery/quickstart.md`
- [X] T035 [P] Add runtime/docs contract sync assertions in `tests/test_workflow_gap_recovery_docs.py`
- [X] T036 Run focused recovery-surface validation suite in `tests/test_final_gate.py`, `tests/test_resolved_thread_validation_gap.py`, `tests/test_issue142_stale_lease_deadlock.py`, `tests/test_agent_resolve_guards.py`, `tests/test_control_plane_fix_all_workflow.py`, `tests/test_python_wrappers.py`, `tests/test_native_foundation.py`, and `tests/test_runtime_packaging.py`
- [X] T037 Run full repo verification stack from `pyproject.toml` and `AGENTS.md` using `pip install -e .`, `ruff check src tests scripts/build_plugin_payload.py`, `python3 -m unittest discover -s tests`, `python3 -m gh_address_cr --help`, `python3 -m gh_address_cr agent manifest`, `python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr`, and `python3 scripts/build_plugin_payload.py --check`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; can begin immediately
- **Foundational (Phase 2)**: Depends on Setup completion; blocks all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational completion; MVP slice
- **User Story 2 (Phase 4)**: Depends on Foundational completion; it is dependency-independent from US1, but rollout-preferred after US1 because it reuses the shared recovery vocabulary
- **User Story 3 (Phase 5)**: Depends on Foundational completion; it is dependency-independent from US1, but rollout-preferred after US1 because final-gate messaging changes build on the new recovery distinctions
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1**: No dependency on other user stories; defines the MVP recovery surface
- **US2**: Depends only on foundational recovery classification; remains independently testable once lease diagnostics are added
- **US3**: Depends only on foundational recovery classification; remains independently testable once telemetry and preflight diagnostics are refined

### Within Each User Story

- Tests for changed behavior MUST be written and fail before implementation
- Runtime fact/projection updates precede gate or CLI surface changes
- Runtime behavior changes precede skill/documentation alignment
- Story-specific docs update only after the runtime truth is in place

### Parallel Opportunities

- **Phase 1**: `T002` and `T003` can run in parallel after `T001`
- **Phase 2**: `T005` and `T006` can run in parallel after `T004`
- **US1**: `T008`, `T009`, `T010`, and `T011` can run in parallel; `T015` and `T016` can proceed in parallel after `T013`
- **US2**: `T018`, `T019`, and `T020` can run in parallel; implementation converges at `T023`
- **US3**: `T026`, `T027`, `T028`, and `T029` can run in parallel; `T030` and `T032` touch different files and can run in parallel once the tests are in place
- **Polish**: `T034` and `T035` can run in parallel before the final validation passes

---

## Parallel Example: User Story 1

```bash
# Launch the US1 regression tests together:
Task: "Add final-gate regression coverage for reconcile-only blockers in tests/test_final_gate.py"
Task: "Add closed-thread validation reconcile coverage in tests/test_resolved_thread_validation_gap.py"
Task: "Add mixed-claimability matching regression for terminal threads in tests/test_control_plane_fix_all_workflow.py"
Task: "Add final-gate regression coverage for explicit non-blocking historical-item classification in tests/test_final_gate.py"

# Launch the two terminal reconcile implementations together after gate routing lands:
Task: "Refine terminal reply-evidence reconcile payloads and session mutations in src/gh_address_cr/core/workflow.py"
Task: "Refine terminal validation-evidence reconcile payloads and guards in src/gh_address_cr/core/workflow.py"
```

## Parallel Example: User Story 2

```bash
# Launch the lease-focused regressions together:
Task: "Add lease-owned blocker regression coverage in tests/test_issue142_stale_lease_deadlock.py"
Task: "Add resolve-mode and item-targeting contract coverage in tests/test_agent_resolve_guards.py"
Task: "Add no-match-vs-lease-locked routing coverage in tests/test_control_plane_fix_all_workflow.py"
```

## Parallel Example: User Story 3

```bash
# Launch the advisory/diagnostic regressions together:
Task: "Add runtime-only advisory guidance regression coverage in tests/test_final_gate.py"
Task: "Add completion-summary and wrapper diagnostic coverage in tests/test_python_wrappers.py"
Task: "Add GitHub preflight diagnostic classification coverage in tests/test_native_foundation.py and tests/test_runtime_packaging.py"
Task: "Add environment-diagnostic payload-shape coverage in tests/test_python_wrappers.py and tests/test_native_foundation.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1
4. Validate terminal-thread recovery end to end using the focused regression suite
5. Stop and review before expanding into lease and environment diagnostics

### Incremental Delivery

1. Land US1 to remove dead-end `final-gate` recovery loops
2. Land US2 to expose authoritative lease recovery guidance
3. Land US3 to clean up diagnostic severity and wrapped-`gh` operator guidance
4. Finish with cross-cutting validation and documentation sync

### Parallel Team Strategy

With multiple contributors:

1. One contributor handles Phase 1 and Phase 2
2. After Foundational completes:
   - Contributor A takes US1 runtime kernel + gate path
   - Contributor B takes US2 lease diagnostics
   - Contributor C takes US3 telemetry and preflight diagnostics
3. Rejoin for Phase 6 verification and doc sync
