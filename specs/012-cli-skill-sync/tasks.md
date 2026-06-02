# Tasks: CLI and Skill Synchronization

**Input**: Design documents from `specs/012-cli-skill-sync/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)
**Status**: Phase 3 closeout complete; Phase 7 records the audit tasks that
aligned the artifacts after the skill-script removal.

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
- [x] T008 [P] [US1] Verify that the current unit-test suite and Ruff check pass

## Phase 5: Refactoring (Phase 2)

- [x] T009 [P] [US2] Create directory `src/gh_address_cr/legacy_handlers/` with `__init__.py`
- [x] T010 [P] [US2] Move `python_common.py` from `src/gh_address_cr/legacy_scripts/` to `src/gh_address_cr/legacy_handlers/`
- [x] T011 [P] [US2] Move all other implementation files from `legacy_scripts/` to `legacy_handlers/` and update internal imports to be package-relative
- [x] T012 [P] [US2] Replace all `src/gh_address_cr/legacy_scripts/` scripts with thin proxies delegating to `gh_address_cr.legacy_handlers`
- [x] T013 [P] [US2] Run `python3 scripts/sync_scripts.py` to sync thin proxies and remove target `python_common.py`
- [x] T014 [P] [US2] Run `python3 scripts/build_plugin_payload.py` to rebuild the plugin skills payload
- [x] T015 [P] [US2] Run Ruff checks and current unittest suite to verify the Phase 2 refactor

## Phase 6: Script Elimination (Phase 3)

- [x] T016 [US3] Update references to shims in `skill/SKILL.md` to point to `gh-address-cr` CLI
- [x] T017 [US3] Update references to shims in `skill/agents/openai.yaml` to point to `gh-address-cr` CLI
- [x] T018 [US3] Delete `skill/scripts/` shims and the directory
- [x] T019 [US3] Delete `scripts/sync_scripts.py`
- [x] T020 [US3] Remove Script sync check from `ci.yml` and `release.yml` and update CLI smoke steps
- [x] T021 [US3] Update `tests/helpers.py` to point `SCRIPTS_DIR` to package-internal legacy scripts
- [x] T022 [US3] Delete `tests/test_skill_runtime_shim.py`
- [x] T023 [US3] Update `tests/test_plugin_packaging.py` and `tests/test_runtime_packaging.py` to remove script check/shim assertions
- [x] T024 [US3] Run `python3 scripts/build_plugin_payload.py` to rebuild plugin payload
- [x] T025 [US3] Run Ruff check and verify the unit test suite passes successfully

## Phase 7: Closeout Audit

- [x] T026 [US3] Update `specs/012-cli-skill-sync/spec.md` to mark `012-skill2cli` Phase 3 complete and remove obsolete sync-era success criteria
- [x] T027 [US3] Update `specs/012-cli-skill-sync/plan.md` to describe the Phase 3 closeout verification gate instead of removed skill-script synchronization
- [x] T028 [US3] Add `tests/test_cli_skill_sync_artifacts.py` to prevent stale `012` artifacts and require superseded markers on older shim-era specs
- [x] T029 [US3] Mark historical specs that still mention `skill/scripts` or `scripts/cli.py` as superseded by `specs/012-cli-skill-sync`
- [x] T030 [US3] Run `ruff check src tests`, `python3 -m unittest discover -s tests`, CLI smoke, manifest smoke, plugin payload check, and `git diff --check`
