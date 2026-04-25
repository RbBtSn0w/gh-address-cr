# Tasks: Runtime Native Refactor

**Input**: Design documents from `specs/002-runtime-native-refactor/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), data-model.md, contracts/

**Tests**: This refactor follows a TDD approach to ensure behavioral parity.

**Organization**: Tasks are grouped by user story to enable incremental migration and verification.

## Phase 1: Setup

**Purpose**: Infrastructure preparation

- [ ] T001 Create native package structure in `src/gh_address_cr/core/`, `src/gh_address_cr/github/`, and `src/gh_address_cr/intake/`
- [ ] T002 [P] Implement base path resolution logic in `src/gh_address_cr/core/paths.py` (extracted from `python_common.py`)
- [ ] T003 [P] Define `Session`, `Item`, `Lease`, and `Finding` TypedDicts in `src/gh_address_cr/core/types.py`

---

## Phase 2: Foundational

**Purpose**: Common utilities used by all stories

- [ ] T004 Implement atomic JSON writer in `src/gh_address_cr/core/io.py`
- [ ] T005 [P] Implement Audit Ledger logging in `src/gh_address_cr/core/ledger.py`
- [ ] T006 [P] Implement GitHub API error types in `src/gh_address_cr/github/errors.py`

---

## Phase 3: User Story 1 - Native Session State Management (Priority: P1)

**Goal**: Migrate session state machine logic to `core`

**Independent Test**: Unit tests for `core.session` and `core.workflow` pass without importing `legacy_scripts`.

### Tests for User Story 1
- [ ] T007 [P] [US1] Create unit tests for session loading/saving in `tests/test_native_session.py`
- [ ] T008 [P] [US1] Create unit tests for state transitions and lease logic in `tests/test_native_workflow.py`

### Implementation for User Story 1
- [ ] T009 [US1] Implement session store in `src/gh_address_cr/core/session.py`
- [ ] T010 [US1] Implement state machine and workflow logic in `src/gh_address_cr/core/workflow.py` (including Principle VI Lease support: expiry, owner tracking, and conflict detection)
- [ ] T011 [US1] Refactor `src/gh_address_cr/cli.py` to use `core.session` and `core.workflow`

---

## Phase 4: User Story 2 - Encapsulated GitHub IO (Priority: P1)

**Goal**: Encapsulate GitHub interaction in a native package

**Independent Test**: `gh_address_cr.github` tests pass with mocks.

### Tests for User Story 2
- [ ] T012 [P] [US2] Create contract tests for GitHub client in `tests/test_native_github.py`

### Implementation for User Story 2
- [ ] T013 [US2] Implement `GitHubClient` in `src/gh_address_cr/github/client.py`
- [ ] T014 [US2] Update `core.workflow` to use native `GitHubClient` instead of `legacy_scripts`

---

## Phase 5: User Story 3 - Native Intake & Findings Normalization (Priority: P1)

**Goal**: Migrate findings normalization logic to `intake`

**Independent Test**: `gh_address_cr.intake` tests verify parity with legacy normalization.

### Tests for User Story 3
- [ ] T015 [P] [US3] Create unit tests for finding normalization in `tests/test_native_intake.py`

### Implementation for User Story 3
- [ ] T016 [US3] Implement findings normalization in `src/gh_address_cr/intake/findings.py`
- [ ] T017 [US3] Update `src/gh_address_cr/cli.py` (review command) to use native `intake`

---

## Phase 6: User Story 4 - Native Final Gate (Priority: P2)

**Goal**: Move Final Gate logic to `core.gate`

**Independent Test**: `core.gate` tests identify blocking items correctly.

### Tests for User Story 4
- [ ] T018 [P] [US4] Create unit tests for final gate policies in `tests/test_native_gate.py`

### Implementation for User Story 4
- [ ] T019 [US4] Implement `Gatekeeper` in `src/gh_address_cr/core/gate.py`
- [ ] T020 [US4] Update `src/gh_address_cr/cli.py` (final-gate command) to use `core.gate`

---

## Phase 7: User Story 5 - Clean Runtime Boundary (Priority: P1)

**Goal**: Eliminate all core dependencies on `legacy_scripts`

**Independent Test**: Full test suite passes when `legacy_scripts` is temporarily renamed.

### Implementation for User Story 5
- [ ] T021 [US5] Audit and remove remaining imports of `legacy_scripts` from `src/gh_address_cr/core/`, `github/`, and `intake/`
- [ ] T022 [US5] Update skill shims in `src/gh_address_cr/legacy_scripts/` to delegate to native packages
- [ ] T023 [US5] Verify all existing tests in `tests/` pass with native implementation

---

## Phase 8: Polish

- [ ] T024 [P] Update `README.md` with new architecture overview
- [ ] T025 [P] Update `quickstart.md` with final verification commands
- [ ] T026 [SC-003] Measure and compare package size with legacy implementation
- [ ] T027 [SC-004] Benchmark execution time (review/final-gate) to verify performance parity
- [ ] T028 Run full regression suite: `python3 -m unittest discover -s tests`

---

## Dependencies & Execution Order

1. **Setup (Phase 1)** & **Foundational (Phase 2)**: Core structure and utilities.
2. **User Story 1 (P1)**: Native session management is the prerequisite for all other logic.
3. **User Story 2 & 3 (P1)**: Can proceed in parallel after Story 1 is complete.
4. **User Story 4 (P2)**: Final gate logic.
5. **User Story 5 (P1)**: Final cleanup and boundary enforcement.
6. **Polish**: Documentation and final regression.
