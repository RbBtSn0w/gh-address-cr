# Tasks: Agent Efficiency Metrics

**Input**: Design documents from `specs/011-agent-efficiency-metrics/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Include test tasks for every behavior, CLI contract, parser, session transition, GitHub side effect, final-gate rule, or packaged-skill contract changed by the feature.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [ ] T001 Define `ExecutionMetric` and `EfficiencyReport` dataclasses in `src/gh_address_cr/core/telemetry.py`
- [ ] T002 Implement `SessionTelemetry` singleton or context manager in `src/gh_address_cr/core/telemetry.py` for in-memory metric storage

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 Create `tests/core/test_telemetry.py` with failing tests for metric recording and reporting logic
- [ ] T004 Implement telemetry tracking wrapper around `run_cmd` in `src/gh_address_cr/core/cr_loop.py`

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Evaluate Workflow Efficiency (Priority: P1) 🎯 MVP

**Goal**: Automatically track and summarize the execution metrics of the AI agent's skills and CLI tools.

**Independent Test**: Execute an agent session and verify that a structured efficiency summary (e.g., tool invocations, duration, success rates) is generated at the end.

### Tests for User Story 1

- [ ] T005 [P] [US1] Add unit tests for `fix_reply` formatting with `efficiency_summary` in `tests/core/test_reply_templates.py`
- [ ] T006 [P] [US1] Add unit tests for total duration and success rate calculation in `tests/core/test_telemetry.py`

### Implementation for User Story 1

- [ ] T007 [P] [US1] Update `fix_reply`, `clarify_reply`, and `defer_reply` signatures in `src/gh_address_cr/core/reply_templates.py` to accept `efficiency_summary`
- [ ] T008 [US1] Implement aggregation logic to generate the human-readable summary string in `src/gh_address_cr/core/telemetry.py`
- [ ] T009 [US1] Wire the generated summary from `SessionTelemetry` to the reply payload generation in `src/gh_address_cr/agent/responses.py`

**Checkpoint**: Basic execution times and success rates are now tracked and appended to replies.

---

## Phase 4: User Story 2 - Flag Inefficiencies (Priority: P1)

**Goal**: Detect and flag operations that fall below expected efficiency standards (execution time > 60s OR error rate > 20%).

**Independent Test**: Mock a tool execution that exceeds the configured duration threshold and verify it is distinctly flagged in the summary report.

### Tests for User Story 2

- [ ] T010 [P] [US2] Add unit tests for threshold evaluations (>60s and >20% error rate) in `tests/core/test_telemetry.py`
- [ ] T011 [P] [US2] Add unit tests for consecutive retry detection in `tests/core/test_telemetry.py`

### Implementation for User Story 2

- [ ] T012 [P] [US2] Define `MAX_DURATION_SECONDS` and `MAX_ERROR_RATE_PERCENT` constants in `src/gh_address_cr/core/telemetry.py`
- [ ] T013 [US2] Implement `evaluate_efficiency` function in `src/gh_address_cr/core/telemetry.py` to identify threshold violations
- [ ] T014 [US2] Update the summary generator in `src/gh_address_cr/core/telemetry.py` to include a "⚠️ Inefficiencies Detected" block if flags exist

**Checkpoint**: Inefficiencies are now automatically highlighted in the generated reply output.

---

## Phase 5: User Story 3 - Export Metrics for Optimization Analysis (Priority: P2)

**Goal**: Export structured workflow metrics (JSON format) across multiple agent sessions.
*(Note: As per clarification, the primary export mechanism is appending to the GitHub PR body. However, ensuring the underlying data model can serialize to JSON supports this long-term goal).*

**Independent Test**: Run a command to extract/export the metrics payload and verify it adheres to a standard JSON schema containing tool execution timings.

### Tests for User Story 3

- [ ] T015 [P] [US3] Add unit tests verifying `EfficiencyReport` and `ExecutionMetric` can be losslessly serialized to JSON in `tests/core/test_telemetry.py`

### Implementation for User Story 3

- [ ] T016 [US3] Add a `.to_dict()` or `.to_json()` method to `EfficiencyReport` in `src/gh_address_cr/core/telemetry.py`

**Checkpoint**: Metrics data structure is ready for potential future programmatic export (e.g., to an OTel relay).

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T017 [P] Update `CHANGELOG.md` with details about the new Agent Efficiency Metrics feature
- [ ] T018 Run `ruff check src tests` to ensure code style compliance
- [ ] T019 Run full test suite `python3 -m unittest discover -s tests` to verify no regressions

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup.
- **User Stories (Phases 3, 4, 5)**: Depend on Foundational.
  - US1 provides the core aggregation, so it should be built before US2.
  - US2 builds upon US1 by adding threshold flagging.
  - US3 is isolated to data serialization and can run parallel to US2.
- **Polish (Final Phase)**: Depends on all user stories.

### Parallel Execution Examples

- While T008 (US1 logic) is being developed, another agent/process could work on T010/T011 (US2 tests) since the entity structure is already defined in Phase 1.
- T017 (Changelog) can be done anytime after the scope is finalized.

---

## Implementation Strategy

### MVP First

The MVP focuses exclusively on **User Story 1**. Getting the interception hook working reliably without crashing the loop, and appending a basic text summary to the reply, proves the architectural integration.

1. Implement `SessionTelemetry` and wrap `run_cmd` (Phase 1 & 2).
2. Wire basic success/duration stats into `fix_reply` (Phase 3).
3. Verify the end-to-end flow with a smoke test before moving on to threshold flags (Phase 4).
