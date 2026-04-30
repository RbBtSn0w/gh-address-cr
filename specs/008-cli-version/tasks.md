---
description: "Task list for CLI version query feature implementation"
---

# Tasks: CLI Version Query

**Input**: Design documents from `/specs/008-cli-version/`
**Prerequisites**: plan.md, spec.md, research.md, contracts/

**Tests**: TDD approach. Write tests for version flags and subcommand before implementation.

**Organization**: Tasks are grouped by user story (US1: Flags, US2: Subcommand).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 [P] Create test file for version query in `tests/test_version_query.py`
- [x] T002 [P] Verify `src/gh_address_cr/__init__.py` exports `__version__`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure prerequisites

- [x] T003 Define public CLI contract for version query in `src/gh_address_cr/cli.py` (imports and basic parser structure)

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Standard Version Flag (Priority: P1) 🎯 MVP

**Goal**: Support `--version` and `-v` global flags

**Independent Test**: Running `gh-address-cr --version` or `gh-address-cr -v` returns the current version string.

### Tests for User Story 1

- [x] T004 [P] [US1] Add unit tests for `--version` flag in `tests/test_version_query.py`
- [x] T005 [P] [US1] Add unit tests for `-v` flag in `tests/test_version_query.py`

### Implementation for User Story 1

- [x] T006 [US1] Add `--version` and `-v` arguments using `action='version'` in `src/gh_address_cr/cli.py`
- [x] T007 [US1] Verify `--version` output format matches `gh-address-cr X.Y.Z`

**Checkpoint**: User Story 1 should be fully functional independently

---

## Phase 4: User Story 2 - Version Subcommand (Priority: P2)

**Goal**: Support `version` subcommand

**Independent Test**: Running `gh-address-cr version` returns the current version string.

### Tests for User Story 2

- [x] T008 [P] [US2] Add unit tests for `version` subcommand in `tests/test_version_query.py`

### Implementation for User Story 2

- [x] T009 [US2] Add `version` to `NATIVE_HIGH_LEVEL_COMMANDS` and `HIGH_LEVEL_COMMANDS` in `src/gh_address_cr/cli.py`
- [x] T010 [US2] Implement `version` command handling in `main` (instead of `handle_native_high_level` because it's simpler and doesn't require repo/pr) within `src/gh_address_cr/cli.py`

**Checkpoint**: User Story 2 should be fully functional independently

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and final validation

- [x] T011 [P] Update `README.md` to include version query examples
- [x] T012 [P] Update `skill/SKILL.md` to include version query examples (if applicable to agent guidance)
- [x] T013 Run quickstart.md validation
- [x] T014 Run `python3 -m unittest discover -s tests`
- [x] T015 Verify version output is consistent across `gh-address-cr` and `python3 skill/scripts/cli.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1
- **User Stories (Phase 3+)**: Depend on Phase 2
- **Polish (Final Phase)**: Depends on US1 and US2 completion

### Parallel Opportunities

- T001 and T002 can run in parallel
- T004, T005, T008 can run in parallel
- T011 and T012 can run in parallel

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup and Foundational
2. Complete User Story 1 (Flags)
3. Validate and commit

### Incremental Delivery

1. Foundation ready
2. Add US1 (Flags) → Test independently
3. Add US2 (Subcommand) → Test independently
4. Polish and final verification
