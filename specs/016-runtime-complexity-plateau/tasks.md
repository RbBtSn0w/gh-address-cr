# Tasks: Runtime Complexity Plateau

**Input**: Design documents from `specs/016-runtime-complexity-plateau/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required. This feature changes public agent contracts, lease/session transitions, telemetry/final-gate behavior, and packaged-skill guidance.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare shared contract fixtures and focused test surfaces without changing runtime behavior.

- [X] T001 Create runtime complexity fixture directory in tests/fixtures/runtime_complexity/
- [X] T002 [P] Add work item handling fixture cases in tests/fixtures/runtime_complexity/work_items.json
- [X] T003 [P] Add lease recovery fixture cases in tests/fixtures/runtime_complexity/lease_recovery.json
- [X] T004 [P] Add logic validation fixture cases in tests/fixtures/runtime_complexity/logic_validation.json
- [X] T005 [P] Add telemetry overhead fixture cases in tests/fixtures/runtime_complexity/telemetry_boundary.json

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define shared runtime models and contract seams that all user stories depend on.

**CRITICAL**: No user story implementation can begin until this phase is complete.

- [X] T006 [P] Add failing model serialization and validation tests in tests/test_runtime_complexity_models.py
- [X] T007 Add WorkItemHandlingBoundary, LeaseRecoveryState, TelemetryCoverageState, LogicValidationSignal, and DeliverySlice model definitions in src/gh_address_cr/core/models.py
- [X] T008 [P] Add failing agent protocol schema compatibility tests for additive recovery and validation fields in tests/test_agent_protocol.py
- [X] T009 Add shared machine-readable reason code constants for boundary, lease recovery, telemetry, and validation outcomes in src/gh_address_cr/core/models.py
- [X] T010 Document foundational contract terms in docs/architecture.md

**Checkpoint**: Runtime has shared data shapes and reason code vocabulary for all stories.

---

## Phase 3: User Story 1 - 拆分可演进的工作项处理边界 (Priority: P1) MVP

**Goal**: Introduce explicit runtime-owned handling boundaries for at least one high-value work item type while preserving public behavior for unmigrated types.

**Independent Test**: A migrated work item type can be selected, rejected, and completed through a deterministic handling boundary with parity against existing user-visible behavior.

### Tests for User Story 1

- [X] T011 [P] [US1] Add contract tests for deterministic boundary selection and conflict rejection in tests/test_work_item_handling_boundaries.py
- [X] T012 [P] [US1] Add parity tests for the first migrated GitHub review-thread handling path in tests/test_control_plane_workflow.py
- [X] T013 [P] [US1] Add unsupported work item fail-fast tests in tests/test_work_item_handling_boundaries.py
- [X] T014 [P] [US1] Add boundary summary contract tests for machine-readable output in tests/test_agent_protocol.py

### Implementation for User Story 1

- [X] T015 [US1] Implement the runtime work item boundary registry in src/gh_address_cr/core/work_item_handlers.py
- [X] T016 [US1] Implement the first GitHub review-thread fix handling boundary in src/gh_address_cr/core/work_item_handlers.py
- [X] T017 [US1] Integrate boundary selection into action request issuance in src/gh_address_cr/core/agent_protocol.py
- [X] T018 [US1] Preserve unmigrated work item behavior through explicit fallback compatibility in src/gh_address_cr/core/agent_protocol.py
- [X] T019 [US1] Add boundary summary fields to agent next/address machine output in src/gh_address_cr/commands/agent.py
- [X] T020 [US1] Update user-facing guidance for boundary summaries in skill/references/agent-protocol.md
- [X] T021 [US1] Run focused US1 validation commands from specs/016-runtime-complexity-plateau/quickstart.md

**Checkpoint**: US1 is independently testable and delivers the MVP boundary model.

---

## Phase 4: User Story 2 - 降低租约过期造成的代理挫败感 (Priority: P1)

**Goal**: Return actionable, machine-readable recovery outcomes for near-expired, expired, stale, transferred, and completed lease submissions.

**Independent Test**: Simulated lease expiration cases return `renew`, `reclaim`, `refresh_state`, `stop`, or `already_completed` without overwriting runtime truth.

### Tests for User Story 2

- [X] T022 [P] [US2] Add lease recovery outcome tests in tests/test_claim_leases.py
- [X] T023 [P] [US2] Add stale request context recovery tests in tests/test_agent_protocol.py
- [X] T024 [P] [US2] Add agent experience regression tests for expired-lease retry loops in tests/test_issue78_agent_experience.py
- [X] T025 [P] [US2] Add lease event audit tests in tests/test_lease_scheduling.py

### Implementation for User Story 2

- [X] T026 [US2] Implement lease recovery outcome calculation in src/gh_address_cr/core/leases.py
- [X] T027 [US2] Add recovery outcome payloads to LeaseSubmissionError handling in src/gh_address_cr/core/agent_protocol.py
- [X] T028 [US2] Surface recovery next actions in agent submit and agent leases commands in src/gh_address_cr/commands/agent.py
- [X] T029 [US2] Preserve runtime truth checks for completed, transferred, and changed work items in src/gh_address_cr/core/leases.py
- [X] T030 [US2] Update Status-to-Action Map guidance for lease recovery in skill/references/status-action-map.md
- [X] T031 [US2] Run focused US2 validation commands from specs/016-runtime-complexity-plateau/quickstart.md

**Checkpoint**: US2 is independently testable and prevents expired lease retry loops.

---

## Phase 5: User Story 3 - 明确 Telemetry 可用性与一致性边界 (Priority: P2)

**Goal**: Enforce telemetry fail-open/fail-loud behavior, source coverage honesty, privacy safety, and the 250ms normal-path overhead budget.

**Independent Test**: Telemetry available, slow, failed, and unsafe cases all produce correct coverage and diagnostics while core review completion remains available.

### Tests for User Story 3

- [X] T032 [P] [US3] Add telemetry overhead budget tests in tests/core/test_telemetry.py
- [X] T033 [P] [US3] Add core-flow fail-open telemetry degradation tests in tests/test_final_gate.py
- [X] T034 [P] [US3] Add telemetry-specific fail-loud command tests in tests/test_telemetry_acceptance_matrix.py
- [X] T035 [P] [US3] Add public-safe diagnostics regression tests in tests/core/test_telemetry.py

### Implementation for User Story 3

- [X] T036 [US3] Add telemetry overhead measurement and budget diagnostics in src/gh_address_cr/core/telemetry.py
- [X] T037 [US3] Integrate coverage degradation diagnostics into final-gate summaries in src/gh_address_cr/commands/final_gate.py
- [X] T038 [US3] Ensure telemetry-specific command failures stay fail-loud in src/gh_address_cr/commands/telemetry.py
- [X] T039 [US3] Preserve source attribution and privacy filtering in public reports in src/gh_address_cr/core/telemetry.py
- [X] T040 [US3] Update telemetry guidance in skill/SKILL.md
- [X] T041 [US3] Run focused US3 validation commands from specs/016-runtime-complexity-plateau/quickstart.md

**Checkpoint**: US3 is independently testable and keeps telemetry useful without blocking core review completion.

---

## Phase 6: User Story 4 - 引入轻量逻辑验证信号 (Priority: P3)

**Goal**: Add advisory-first validation signals that catch evidence gaps and state contradictions without becoming a second review producer.

**Independent Test**: Evidence gaps, state contradictions, over-completion claims, and normal completions produce correct advisory or blocking signal outcomes.

### Tests for User Story 4

- [X] T042 [P] [US4] Add logic validation signal tests in tests/test_logic_validation.py
- [X] T043 [P] [US4] Add final-gate blocking signal tests in tests/test_final_gate.py
- [X] T044 [P] [US4] Add low-confidence advisory non-blocking tests in tests/test_logic_validation.py
- [X] T045 [P] [US4] Add no-state-mutation tests for validation signals in tests/test_logic_validation.py

### Implementation for User Story 4

- [X] T046 [US4] Implement logic validation signal generation in src/gh_address_cr/core/logic_validation.py
- [X] T047 [US4] Integrate validation signals into final-gate diagnostics in src/gh_address_cr/core/gate.py
- [X] T048 [US4] Surface validation signal summaries in final-gate CLI output in src/gh_address_cr/commands/final_gate.py
- [X] T049 [US4] Add agent-facing guidance for validation signals in skill/references/completion-contract.md
- [X] T050 [US4] Run focused US4 validation commands from specs/016-runtime-complexity-plateau/quickstart.md

**Checkpoint**: US4 is independently testable and improves gate quality without replacing evidence-first handling.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verify the feature across contracts, docs, package boundaries, and full repository checks.

- [X] T051 [P] Update CLI reference examples for new additive fields in docs/cli-reference.md
- [X] T052 [P] Update architecture documentation for final handler, lease, telemetry, and validation boundaries in docs/architecture.md
- [X] T053 [P] Update packaged skill documentation tests in tests/test_skill_docs.py
- [X] T054 Verify repo-root versus skill-root path language in docs/ and skill/
- [X] T055 Run quickstart validation scenarios in specs/016-runtime-complexity-plateau/quickstart.md
- [X] T056 Run ruff check src tests from repository root
- [X] T057 Run python3 -m unittest discover -s tests from repository root
- [X] T058 Run python3 -m gh_address_cr --help from repository root

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; can start immediately.
- **Foundational (Phase 2)**: Depends on Setup; blocks all user stories.
- **US1 (Phase 3)**: Depends on Foundational; recommended MVP.
- **US2 (Phase 4)**: Depends on Foundational; can run after or alongside US1 once shared model fields exist.
- **US3 (Phase 5)**: Depends on Foundational; can run independently after telemetry model fields exist.
- **US4 (Phase 6)**: Depends on Foundational; can run independently after validation signal model fields exist, but final-gate integration should account for US3 if both touch final-gate output.
- **Polish (Phase 7)**: Depends on selected user stories being complete.

### User Story Dependencies

- **US1**: No dependency on other stories; MVP because it proves the boundary model and reduces core branching pressure.
- **US2**: No direct dependency on US1, but shares agent protocol payload conventions from Phase 2.
- **US3**: No dependency on US1/US2, but final-gate output changes must be reconciled with US4 if both are implemented.
- **US4**: No dependency on US1/US2/US3, but final-gate diagnostics should compose with telemetry coverage output.

### Within Each User Story

- Write tests first and confirm they fail before implementation.
- Implement runtime behavior before updating skill guidance.
- Update machine-readable output before documentation examples.
- Run focused quickstart validation before moving to the next story.

## Parallel Opportunities

- T002, T003, T004, and T005 can run in parallel.
- T006 and T008 can run in parallel as foundational RED tests.
- T010 can run in parallel after T006 and T008 define the expected terminology.
- US1 test tasks T011 through T014 can run in parallel.
- US2 test tasks T022 through T025 can run in parallel.
- US3 test tasks T032 through T035 can run in parallel.
- US4 test tasks T042 through T045 can run in parallel.
- Documentation polish tasks T051 through T053 can run in parallel after their related story docs are complete.

## Parallel Example: User Story 1

```bash
Task: "T011 [P] [US1] Add contract tests for deterministic boundary selection and conflict rejection in tests/test_work_item_handling_boundaries.py"
Task: "T012 [P] [US1] Add parity tests for the first migrated GitHub review-thread handling path in tests/test_control_plane_workflow.py"
Task: "T013 [P] [US1] Add unsupported work item fail-fast tests in tests/test_work_item_handling_boundaries.py"
Task: "T014 [P] [US1] Add boundary summary contract tests for machine-readable output in tests/test_agent_protocol.py"
```

## Parallel Example: User Story 2

```bash
Task: "T022 [P] [US2] Add lease recovery outcome tests in tests/test_claim_leases.py"
Task: "T023 [P] [US2] Add stale request context recovery tests in tests/test_agent_protocol.py"
Task: "T024 [P] [US2] Add agent experience regression tests for expired-lease retry loops in tests/test_issue78_agent_experience.py"
Task: "T025 [P] [US2] Add lease event audit tests in tests/test_lease_scheduling.py"
```

## Parallel Example: User Story 3

```bash
Task: "T032 [P] [US3] Add telemetry overhead budget tests in tests/core/test_telemetry.py"
Task: "T033 [P] [US3] Add core-flow fail-open telemetry degradation tests in tests/test_final_gate.py"
Task: "T034 [P] [US3] Add telemetry-specific fail-loud command tests in tests/test_telemetry_acceptance_matrix.py"
Task: "T035 [P] [US3] Add public-safe diagnostics regression tests in tests/core/test_telemetry.py"
```

## Parallel Example: User Story 4

```bash
Task: "T042 [P] [US4] Add logic validation signal tests in tests/test_logic_validation.py"
Task: "T043 [P] [US4] Add final-gate blocking signal tests in tests/test_final_gate.py"
Task: "T044 [P] [US4] Add low-confidence advisory non-blocking tests in tests/test_logic_validation.py"
Task: "T045 [P] [US4] Add no-state-mutation tests for validation signals in tests/test_logic_validation.py"
```

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1 and Phase 2.
2. Complete US1 tests and implementation.
3. Validate work item boundary parity and fail-fast handling.
4. Stop and review whether the boundary contract is stable enough before migrating additional types.

### Incremental Delivery

1. Deliver US1 to reduce core workflow branching pressure.
2. Deliver US2 to reduce agent retry loops and stale lease confusion.
3. Deliver US3 to make telemetry overhead and coverage behavior explicit.
4. Deliver US4 to improve final-gate diagnostic quality.
5. Run Phase 7 checks after each selected slice before claiming completion.

### Parallel Team Strategy

After Phase 2, separate agents can work on US1, US2, US3, and US4 tests in parallel because they touch separate initial test files. Coordinate final-gate output edits in `src/gh_address_cr/core/gate.py` and `src/gh_address_cr/commands/final_gate.py` to avoid conflicting summaries.

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- Public CLI and machine-readable field changes must be documented and tested in the same story phase.
- Do not add hidden compatibility shims; preserve or version public behavior explicitly.
