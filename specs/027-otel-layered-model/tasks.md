---

description: "Task list for layered OTel workflow modeling"
---

# Tasks: Layered OTel Workflow Modeling

**Input**: Design documents from `/specs/027-otel-layered-model/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Include test tasks for every changed telemetry behavior, root/child/event contract boundary, and CLI-visible no-regression guarantee.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (`US1`, `US2`, `US3`)
- Every task includes an exact file path

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish task-scoped spec artifacts and verify the current runtime surfaces to change

- [X] T001 Capture the current event-only workflow boundaries in `specs/027-otel-layered-model/research.md`
- [X] T002 Verify target runtime surfaces and note first-slice scope in `specs/027-otel-layered-model/plan.md`
- [X] T003 [P] Record validation commands and expected runtime checks in `specs/027-otel-layered-model/quickstart.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared telemetry infrastructure and contract updates required before any user story work

**⚠️ CRITICAL**: No user story work should begin until this phase is complete

- [X] T004 Define stable child-span naming and parentage rules in `specs/027-otel-layered-model/contracts/workflow-layering-contract.md`
- [X] T005 [P] Add shared telemetry helper support for layered child spans in `src/gh_address_cr/telemetry.py`
- [X] T006 [P] Add or update shared semantic/attribute helpers for child operations in `src/gh_address_cr/core/otel_semconv.py`
- [X] T007 [P] Add classification helpers for root span vs child span vs event candidates in `src/gh_address_cr/core/telemetry_safety.py`
- [X] T008 Add foundational regression coverage for layered telemetry helpers in `tests/test_otel_telemetry.py`
- [X] T009 Add or update public contract stability coverage for telemetry contract docs in `tests/contract/test_public_contract_stability.py`

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Decide Whether the Layered Model Becomes the Default (Priority: P1) 🎯 MVP

**Goal**: Encode the default layered telemetry model in runtime code and prove the first implementation slice uses child spans only for truly independent operations

**Independent Test**: A reviewer can inspect the updated contract and runtime tests and confirm the implementation preserves one root invocation span while promoting only the approved first-slice operations to child spans

### Tests for User Story 1

- [X] T010 [P] [US1] Add root-span preservation and child-parentage tests in `tests/test_cli_otel_execution.py`
- [X] T011 [P] [US1] Add adapter child-span contract tests in `tests/test_telemetry_acceptance_matrix.py`
- [X] T012 [P] [US1] Add command-session child-span contract tests in `tests/test_telemetry_acceptance_matrix.py`

### Implementation for User Story 1

- [X] T013 [US1] Refactor adapter execution to emit a child span instead of only start/end events in `src/gh_address_cr/commands/high_level.py`
- [X] T014 [US1] Refactor command-session per-operation execution to emit child spans in `src/gh_address_cr/commands/command_session.py`
- [X] T015 [US1] Keep root invocation span ownership and child-span wiring consistent in `src/gh_address_cr/__main__.py`
- [X] T016 [US1] Update the layered workflow contract with the approved first-slice child spans in `specs/027-otel-layered-model/contracts/workflow-layering-contract.md`
- [X] T017 [US1] Record the architectural keep/revise/reject decision and first-slice rationale in `specs/027-otel-layered-model/research.md`

**Checkpoint**: User Story 1 should preserve the root span and promote only adapter and command-session operation boundaries as child spans

---

## Phase 4: User Story 2 - Preserve Queryable Workflow Metrics Without Losing Product Timelines (Priority: P2)

**Goal**: Preserve Honeycomb-readable timeline sequencing while keeping checkpoint-style workflow narration as events

**Independent Test**: For a representative workflow path, tests show child spans exist for independent operations while preflight/session/ingest/gate style checkpoints remain events on the correct active span

### Tests for User Story 2

- [X] T018 [P] [US2] Add checkpoint-event retention tests for high-level workflow phases in `tests/test_telemetry_acceptance_matrix.py`
- [X] T019 [P] [US2] Add no-regression coverage for session correlation and root timeline attributes in `tests/test_cli_otel_context.py`
- [X] T020 [P] [US2] Add CLI-visible GenAI/VCS telemetry regression coverage alongside layered spans in `tests/test_cli_otel_genai.py`

### Implementation for User Story 2

- [X] T021 [US2] Retain or tighten event-only modeling for checkpoint phases in `src/gh_address_cr/commands/high_level.py`
- [X] T022 [US2] Ensure command-session summary and checkpoint events remain attached to the correct active span in `src/gh_address_cr/commands/command_session.py`
- [X] T023 [US2] Update validation scenarios for queryable child spans versus event checkpoints in `specs/027-otel-layered-model/quickstart.md`
- [X] T024 [US2] Update the data model to reflect the final event-versus-child-span ownership after implementation in `specs/027-otel-layered-model/data-model.md`

**Checkpoint**: User Story 2 should make invocation count, child-operation latency, and checkpoint sequencing simultaneously observable without turning every phase into a span

---

## Phase 5: User Story 3 - Give Contributors a Stable Promotion Rule for Spans vs Events (Priority: P3)

**Goal**: Make future telemetry changes reviewable with a durable promotion rule instead of ad hoc reviewer preference

**Independent Test**: A contributor can use the updated docs/tests to classify representative workflow elements as root-span data, child spans, or events without consulting implementation-only context

### Tests for User Story 3

- [X] T025 [P] [US3] Add classification-rule regression coverage for representative workflow elements in `tests/test_telemetry_acceptance_matrix.py`
- [X] T026 [P] [US3] Add contract stability coverage for contributor-facing telemetry guidance in `tests/contract/test_public_contract_stability.py`

### Implementation for User Story 3

- [X] T027 [US3] Encode the final promotion rule and exception policy in `specs/027-otel-layered-model/spec.md`
- [X] T028 [US3] Update the contract with contributor review rules for new telemetry additions in `specs/027-otel-layered-model/contracts/workflow-layering-contract.md`
- [X] T029 [US3] Update the plan/data model references so future reviewers can map workflow elements consistently in `specs/027-otel-layered-model/data-model.md`
- [X] T030 [US3] Add maintainer-facing inline guidance for layered telemetry call sites in `src/gh_address_cr/telemetry.py`

**Checkpoint**: All representative workflow elements should be classifiable by rule, not by case-by-case interpretation

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final verification, cleanup, and cross-story consistency

- [X] T031 [P] Refresh implementation notes and evidence after code completion in `specs/027-otel-layered-model/research.md`
- [X] T032 [P] Run focused layered telemetry validation from `specs/027-otel-layered-model/quickstart.md`
- [X] T033 Run `ruff check src tests scripts/build_plugin_payload.py`
- [X] T034 Run `python3 -m unittest discover -s tests`
- [X] T035 Run `python3 -m gh_address_cr --help`
- [X] T036 Run `python3 -m gh_address_cr agent manifest`
- [X] T037 Run `python3 scripts/build_plugin_payload.py --check`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies
- **Phase 2 (Foundational)**: Depends on Phase 1 and blocks all user stories
- **Phase 3 (US1)**: Depends on Phase 2 and defines the MVP
- **Phase 4 (US2)**: Depends on Phase 2 and should build on the child-span foundations from US1
- **Phase 5 (US3)**: Depends on Phase 2 and should finalize the classification rule after US1/US2 behavior is concrete
- **Phase 6 (Polish)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1**: Starts after Foundational; no dependency on other user stories
- **US2**: Starts after Foundational, but should be integrated after US1 child-span surfaces exist
- **US3**: Starts after Foundational, but should finalize docs/rules after US1 and US2 settle the runtime shape

### Within Each User Story

- Tests for changed behavior first
- Shared helper/code-surface changes before call-site rewiring
- Runtime implementation before doc/contract finalization
- Story verification before moving to the next priority

### Parallel Opportunities

- `T005`, `T006`, and `T007` can run in parallel after `T004`
- `T010`, `T011`, and `T012` can run in parallel
- `T018`, `T019`, and `T020` can run in parallel
- `T025` and `T026` can run in parallel
- `T031` and `T032` can run in parallel once implementation is complete

---

## Parallel Example: User Story 1

```bash
# Launch US1 failing tests together:
Task: "Add root-span preservation and child-parentage tests in tests/test_cli_otel_execution.py"
Task: "Add adapter child-span contract tests in tests/test_telemetry_acceptance_matrix.py"
Task: "Add command-session child-span contract tests in tests/test_telemetry_acceptance_matrix.py"

# Then implement the independent runtime surfaces:
Task: "Refactor adapter execution to emit a child span instead of only start/end events in src/gh_address_cr/commands/high_level.py"
Task: "Refactor command-session per-operation execution to emit child spans in src/gh_address_cr/commands/command_session.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup
2. Complete Foundational
3. Complete US1
4. Validate retained root span + first-slice child spans
5. Stop and review the resulting shape before broadening scope

### Incremental Delivery

1. Foundation: shared helpers and contract scaffolding
2. US1: promote the least ambiguous independent operations
3. US2: preserve timeline readability and event retention
4. US3: finalize contributor rules and documentation
5. Polish: run full verification and contract checks

### Parallel Team Strategy

1. One engineer handles shared telemetry helpers and tests in Phase 2
2. One engineer handles adapter child-span work
3. One engineer handles command-session child-span work
4. After runtime shape stabilizes, documentation/contract finalization can proceed in parallel with final verification
