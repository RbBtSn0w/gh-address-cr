# Tasks: Action Request Friction Repair

**Input**: Design documents from `/specs/009-action-request-friction/`  
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required for helper schema compatibility, runtime error guidance, batch all-or-nothing behavior, and documentation/skill contract consistency.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm active feature context and baseline behavior before changing code.

- [x] T001 Run baseline `python3 -m unittest discover -s tests` and record current status for TDD gate
- [x] T002 [P] Inspect current helper and runtime protocol surfaces in `skill/scripts/submit_action.py`, `src/gh_address_cr/legacy_scripts/submit_action.py`, `src/gh_address_cr/core/workflow.py`, and `README.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add regression tests before implementation.

- [x] T003 [P] Add helper tests for runtime `ActionRequest.repository_context` parsing and legacy top-level request compatibility in `tests/test_submit_action_helper.py`
- [x] T004 [P] Add helper malformed-request tests for missing repository context, missing item, and missing runtime request identity in `tests/test_submit_action_helper.py`
- [x] T005 [P] Add runtime workflow tests for missing classification and missing resolution guidance in `tests/test_control_plane_workflow.py`
- [x] T006 [P] Extend batch response tests for all-or-nothing invalid mixed item rejection in `tests/test_control_plane_workflow.py`

**Checkpoint**: Required regression tests exist and fail before implementation.

---

## Phase 3: User Story 1 - Submit Runtime Action Requests (Priority: P1)

**Goal**: The helper accepts runtime-generated request artifacts and writes valid structured response artifacts.

**Independent Test**: `python3 -m unittest tests.test_submit_action_helper`

### Implementation for User Story 1

- [x] T007 [US1] Implement request context extraction and runtime-vs-legacy request detection in `skill/scripts/submit_action.py`
- [x] T008 [US1] Generate structured `ActionResponse` artifacts for runtime requests in `skill/scripts/submit_action.py`
- [x] T009 [US1] Mirror helper compatibility changes in `src/gh_address_cr/legacy_scripts/submit_action.py`
- [x] T010 [US1] Ensure helper output and no-resume instructions point to `gh-address-cr agent submit` for runtime requests in `skill/scripts/submit_action.py` and `src/gh_address_cr/legacy_scripts/submit_action.py`

**Checkpoint**: Runtime ActionRequest and legacy loop request helper tests pass.

---

## Phase 4: User Story 2 - Understand Classification and Submission Fields (Priority: P2)

**Goal**: Agents receive unambiguous guidance for triage classification and fixer resolution failures.

**Independent Test**: Targeted workflow tests in `tests/test_control_plane_workflow.py`

### Implementation for User Story 2

- [x] T011 [US2] Update missing classification `WorkflowError` next-action payload in `src/gh_address_cr/core/workflow.py`
- [x] T012 [US2] Update missing response field handling for `resolution` guidance in `src/gh_address_cr/core/workflow.py`
- [x] T013 [US2] Document classification-vs-resolution phases in `README.md` and `skill/SKILL.md`

**Checkpoint**: Classification and resolution guidance tests pass independently.

---

## Phase 5: User Story 3 - Batch Small GitHub Thread Fixes (Priority: P3)

**Goal**: The batch path is discoverable and proven safe for multiple small GitHub-thread fixes.

**Independent Test**: Batch workflow tests in `tests/test_control_plane_workflow.py`

### Implementation for User Story 3

- [x] T014 [US3] Preserve all-or-nothing batch rejection behavior while covering mixed invalid items in `src/gh_address_cr/core/workflow.py`
- [x] T015 [US3] Clarify `submit-batch` usage, constraints, and max-claim rationale in `README.md`
- [x] T016 [US3] Clarify packaged skill guidance for small thread batches in `skill/SKILL.md`

**Checkpoint**: Batch acceptance and rejection tests pass independently.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validate contracts, docs, and complete the speckit feature.

- [x] T017 [P] Verify repo-root vs skill-root path language in `README.md`, `skill/SKILL.md`, and `specs/009-action-request-friction/contracts/`
- [x] T018 Run `ruff check src tests`
- [x] T019 Run `python3 -m unittest discover -s tests`
- [x] T020 Run CLI smoke checks `python3 -m gh_address_cr --help` and `python3 skill/scripts/cli.py --help`
- [x] T021 Sync spec status to Verified only after tests, lint, and spec coverage pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup completion and blocks implementation.
- **User Story 1 (Phase 3)**: Depends on Foundational tests.
- **User Story 2 (Phase 4)**: Depends on Foundational tests.
- **User Story 3 (Phase 5)**: Depends on Foundational tests.
- **Polish (Phase 6)**: Depends on selected user stories being complete.

### User Story Dependencies

- **US1**: Highest priority because it removes the blocking schema mismatch.
- **US2**: Can be implemented after tests are in place; no dependency on US1 code.
- **US3**: Mostly documentation and regression proof around existing batch runtime behavior; can be implemented after tests are in place.

### Parallel Opportunities

- T003, T004, T005, and T006 can be written in parallel because they cover separate test surfaces.
- US2 documentation updates and US3 documentation updates can be reviewed independently after runtime wording is settled.
- T018, T019, and T020 are sequential final gates because later claims depend on fresh output.

## Implementation Strategy

### MVP First

1. Complete setup and failing tests.
2. Complete US1 to remove the blocking request schema mismatch.
3. Validate `tests.test_submit_action_helper`.

### Incremental Delivery

1. Add US2 wording and guidance once helper compatibility is green.
2. Add US3 batch documentation and safety regression coverage.
3. Run full lint, unit tests, and CLI smoke checks.
