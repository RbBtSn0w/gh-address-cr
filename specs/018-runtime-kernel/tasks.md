# Tasks: Runtime Kernel

**Input**: Design documents from `specs/018-runtime-kernel/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/
**Tests**: Required. This runtime-kernel feature must prove fact validation, deterministic projection, deterministic policy, idempotent side-effect plans, final-gate blocking, and telemetry/reporting boundary behavior.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the package boundary without adding behavior before RED tests.

- [x] T001 Create runtime-kernel package exports in src/gh_address_cr/core/runtime_kernel/__init__.py
- [x] T002 [P] Create empty runtime-kernel module shells in src/gh_address_cr/core/runtime_kernel/events.py, src/gh_address_cr/core/runtime_kernel/projections.py, src/gh_address_cr/core/runtime_kernel/policies.py, and src/gh_address_cr/core/runtime_kernel/commands.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish shared kernel vocabulary and test target ownership before user-story behavior.

- [x] T003 Define shared test helpers for runtime-kernel fact dictionaries in tests/test_runtime_kernel.py
- [x] T004 Record the no-public-CLI-change assertion in tests/test_runtime_kernel.py by importing only internal runtime-kernel modules

**Checkpoint**: Foundation ready. User-story tasks can now run in priority order.

---

## Phase 3: User Story 1 - Project Review State From Facts (Priority: P1) MVP

**Goal**: Provide deterministic runtime facts and review-thread projection.

**Independent Test**: `python3 -m unittest tests.test_runtime_kernel.RuntimeKernelProjectionTests`

### Tests for User Story 1

- [x] T005 [P] [US1] Write RED tests for RuntimeFact validation and stable fact ordering in tests/test_runtime_kernel.py
- [x] T006 [P] [US1] Write RED tests proving same facts and reordered facts produce identical ReviewProjection dictionaries in tests/test_runtime_kernel.py
- [x] T007 [P] [US1] Write RED tests for unresolved, stale, reopened, and already-resolved thread projection states in tests/test_runtime_kernel.py

### Implementation for User Story 1

- [x] T008 [US1] Implement RuntimeFact, ReviewThreadFact, CommandExecutionFact, and fact sorting in src/gh_address_cr/core/runtime_kernel/events.py
- [x] T009 [US1] Implement ReviewWorkItem, ReviewProjection, and projection serialization in src/gh_address_cr/core/runtime_kernel/projections.py
- [x] T010 [US1] Implement deterministic review-thread projection using src/gh_address_cr/core/github_thread_state.py semantics in src/gh_address_cr/core/runtime_kernel/projections.py

**Checkpoint**: US1 projection tests pass independently and no public CLI behavior is changed.

---

## Phase 4: User Story 2 - Decide The Next Runtime Action (Priority: P2)

**Goal**: Map a projected review state to exactly one deterministic policy decision.

**Independent Test**: `python3 -m unittest tests.test_runtime_kernel.RuntimeKernelPolicyTests`

### Tests for User Story 2

- [x] T011 [P] [US2] Write RED tests for blocked, ready_for_action, waiting_for_external_input, and final_gate_eligible decisions in tests/test_runtime_kernel.py
- [x] T012 [P] [US2] Write RED test proving final-gate cannot be eligible when unresolved or evidence-pending review work remains in tests/test_runtime_kernel.py

### Implementation for User Story 2

- [x] T013 [US2] Implement PolicyDecision and evaluate_review_policy in src/gh_address_cr/core/runtime_kernel/policies.py
- [x] T014 [US2] Export policy decision vocabulary from src/gh_address_cr/core/runtime_kernel/__init__.py

**Checkpoint**: US1 and US2 tests pass independently with deterministic decision dictionaries.

---

## Phase 5: User Story 3 - Plan Side Effects Without Performing Them (Priority: P3)

**Goal**: Produce idempotent command plans and keep planned side effects separate from completion evidence.

**Independent Test**: `python3 -m unittest tests.test_runtime_kernel.RuntimeKernelCommandPlanTests`

### Tests for User Story 3

- [x] T015 [P] [US3] Write RED tests proving command plans are idempotent and non-executing in tests/test_runtime_kernel.py
- [x] T016 [P] [US3] Write RED tests proving planned commands do not satisfy completion until matching successful command execution facts are projected in tests/test_runtime_kernel.py
- [x] T017 [P] [US3] Write RED tests proving reporting-only facts do not complete review work or create recursive blockers in tests/test_runtime_kernel.py

### Implementation for User Story 3

- [x] T018 [US3] Implement PlannedCommand and plan_review_commands in src/gh_address_cr/core/runtime_kernel/commands.py
- [x] T019 [US3] Integrate successful CommandExecutionFact evidence into ReviewProjection completion semantics in src/gh_address_cr/core/runtime_kernel/projections.py
- [x] T020 [US3] Ignore reporting_observed facts for completion while preserving diagnostics in src/gh_address_cr/core/runtime_kernel/projections.py
- [x] T021 [US3] Export command-planning vocabulary from src/gh_address_cr/core/runtime_kernel/__init__.py

**Checkpoint**: All user stories pass independently and command planning remains side-effect free.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validate contract consistency, repository checks, and completion evidence.

- [x] T022 [P] Verify specs/018-runtime-kernel/contracts/review-thread-kernel.md matches the implemented fact, projection, and policy vocabulary
- [x] T023 [P] Verify specs/018-runtime-kernel/contracts/command-plan.md matches the implemented PlannedCommand fields and idempotency behavior
- [x] T024 [P] Verify specs/018-runtime-kernel/contracts/telemetry-reporting-boundary.md matches reporting_observed behavior
- [x] T025 Run focused validation command `python3 -m unittest tests.test_runtime_kernel`
- [x] T026 Run lint command `ruff check src tests`
- [x] T027 Run full unit suite `python3 -m unittest discover -s tests`
- [x] T028 Run CLI smoke command `python3 -m gh_address_cr --help`
- [x] T029 Prepare a draft Conventional Commit message without staging or committing unless explicitly authorized

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup completion and blocks all user stories.
- **User Story 1 (P1)**: Depends on Foundational completion.
- **User Story 2 (P2)**: Depends on US1 projection objects.
- **User Story 3 (P3)**: Depends on US1 projection objects and US2 policy decisions.
- **Polish (Phase 6)**: Depends on all desired user stories being complete.

### User Story Dependencies

- **US1** is the MVP and can be validated independently after T010.
- **US2** depends on US1 only for projection inputs.
- **US3** depends on US1 and US2 because command planning consumes both projection and decision.

### Within Each User Story

- Write RED tests before production code.
- Run the independent test command for the story after GREEN.
- Keep projection, policy, and command planning in separate modules.
- Do not add public CLI behavior in this slice.

## Parallel Opportunities

- T002 can run in parallel with T001 after the package directory exists.
- T005, T006, and T007 can be written together because they target distinct test methods.
- T011 and T012 can be written together because they target policy behavior.
- T015, T016, and T017 can be written together because they target command-plan and reporting boundary behavior.
- T022, T023, and T024 can be verified in parallel after implementation.

## Parallel Example: User Story 1

```bash
Task: "Write RED tests for RuntimeFact validation and stable fact ordering in tests/test_runtime_kernel.py"
Task: "Write RED tests proving same facts and reordered facts produce identical ReviewProjection dictionaries in tests/test_runtime_kernel.py"
Task: "Write RED tests for unresolved, stale, reopened, and already-resolved thread projection states in tests/test_runtime_kernel.py"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup and Foundational phases.
2. Write and run US1 RED tests.
3. Implement facts and projection until US1 tests pass.
4. Stop and validate `python3 -m unittest tests.test_runtime_kernel.RuntimeKernelProjectionTests`.

### Incremental Delivery

1. Add US1 projection determinism.
2. Add US2 policy determinism.
3. Add US3 command planning and evidence/reporting boundary.
4. Run focused, lint, full unit, and CLI smoke validation.

## Notes

- Planned commands are not side effects and must not call GitHub, write artifacts, mutate sessions, or archive workspaces.
- Existing session and artifact files remain compatibility/reporting surfaces unless explicitly modeled as versioned fact sources in a later feature.
- The final commit step is intentionally represented as a draft message because AGENTS.md forbids staging or committing without explicit user authorization.
