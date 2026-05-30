# Tasks: CLI and Skill Synchronization

**Input**: Design documents from `specs/012-cli-skill-sync/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)

## Phase 1: Setup

- [x] T001 [P] [US1] Create `scripts/sync_scripts.py` to support synchronization and dry-run drift check

## Phase 2: Foundational

- [x] T002 [US1] Add the sync check test `test_skill_scripts_are_synchronized_with_legacy_scripts` in `tests/test_plugin_packaging.py`

## Phase 3: Integration

- [x] T003 [P] [US2] Add `Script sync check` step in `.github/workflows/ci.yml`
- [x] T004 [P] [US2] Add `Script sync check` step in `.github/workflows/release.yml`

## Phase 4: Polish (Phase 1)

- [x] T005 [P] [US1] Run `python3 scripts/sync_scripts.py` to synchronize all scripts
- [x] T006 [P] [US1] Run `python3 scripts/build_plugin_payload.py` to rebuild the plugin skills payload
- [x] T007 [P] [US1] Update `test_python_wrappers.py` assertions to align with native final-gate diagnostic counts and log messages
- [x] T008 [P] [US1] Verify that all 544 tests pass successfully and Ruff check passes

## Phase 5: Refactoring (Phase 2)

- [x] T009 [P] [US2] Create directory `src/gh_address_cr/legacy_handlers/` with `__init__.py`
- [x] T010 [P] [US2] Move `python_common.py` from `src/gh_address_cr/legacy_scripts/` to `src/gh_address_cr/legacy_handlers/`
- [x] T011 [P] [US2] Move all other implementation files from `legacy_scripts/` to `legacy_handlers/` and update internal imports to be package-relative
- [x] T012 [P] [US2] Replace all `src/gh_address_cr/legacy_scripts/` scripts with thin proxies delegating to `gh_address_cr.legacy_handlers`
- [x] T013 [P] [US2] Run `python3 scripts/sync_scripts.py` to sync thin proxies and remove target `python_common.py`
- [x] T014 [P] [US2] Run `python3 scripts/build_plugin_payload.py` to rebuild the plugin skills payload
- [x] T015 [P] [US2] Run Ruff checks and unittest suite to verify all 544 tests pass
