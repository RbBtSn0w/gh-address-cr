# Tasks: CLI and Skill Synchronization

**Input**: Design documents from `specs/012-cli-skill-sync/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)

## Phase 1: Setup

- [x] T001 [P] Create `scripts/sync_scripts.py` to support synchronization and dry-run drift check

## Phase 2: Foundational

- [x] T002 Add the sync check test `test_skill_scripts_are_synchronized_with_legacy_scripts` in `tests/test_plugin_packaging.py`

## Phase 3: Integration

- [x] T003 [P] Add `Script sync check` step in `.github/workflows/ci.yml`
- [x] T004 [P] Add `Script sync check` step in `.github/workflows/release.yml`

## Phase 4: Polish

- [x] T005 [P] Run `python3 scripts/sync_scripts.py` to synchronize all scripts
- [x] T006 [P] Run `python3 scripts/build_plugin_payload.py` to rebuild the plugin skills payload
- [x] T007 [P] Update `test_python_wrappers.py` assertions to align with native final-gate diagnostic counts and log messages
- [x] T008 [P] Verify that all 544 tests pass successfully and Ruff check passes
