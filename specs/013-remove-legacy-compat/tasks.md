# Tasks: Remove Legacy Compatibility

**Input**: Design documents from `specs/013-remove-legacy-compat/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/
**Tests**: Required. This feature changes CLI contracts, package contents, active guidance, and fail-fast behavior.
**Organization**: Tasks are grouped by user story to enable independently testable increments.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the active feature and baseline before changing contracts.

- [X] T001 Run baseline `python3 -m unittest tests.test_runtime_packaging tests.test_native_runtime_boundary tests.test_python_wrappers tests.test_skill_docs tests.test_plugin_packaging` and record RED/GREEN baseline for `specs/013-remove-legacy-compat/quickstart.md`
- [X] T002 [P] Inspect current CLI routing and package-data boundaries in `src/gh_address_cr/cli.py` and `pyproject.toml`
- [X] T003 [P] Inspect active skill and plugin guidance for historical script references in `skill/SKILL.md`, `skill/agents/openai.yaml`, `skill/references/`, and `plugin/gh-address-cr/skills/gh-address-cr/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the executable removal contract before user stories.

- [X] T004 [P] Add failing package contract tests that reject `src/gh_address_cr/legacy_scripts/` runtime package dependency in `tests/test_runtime_packaging.py`
- [X] T005 [P] Add failing CLI contract tests that require `cr-loop`, `session-engine`, and `clean-state` to fail as unsupported legacy commands without creating session state in `tests/test_runtime_packaging.py`
- [X] T006 [P] Add failing native-boundary tests that prove supported current commands still run when `legacy_scripts` is absent in `tests/test_native_runtime_boundary.py`
- [X] T007 [P] Add failing active-guidance tests that reject unmarked legacy script instructions in `tests/test_skill_docs.py`

**Checkpoint**: Removal contract is RED and implementation can begin.

---

## Phase 3: User Story 1 - Use Only Current Supported Workflows (Priority: P1) MVP

**Goal**: Current documented workflows run without legacy script dispatcher evaluation.

**Independent Test**: Current command help and high-level workflow tests pass while package tests prove the runtime no longer carries or dispatches `legacy_scripts`.

### Tests for User Story 1

- [X] T008 [P] [US1] Update current command help parity tests for supported commands only in `tests/test_runtime_packaging.py`
- [X] T009 [P] [US1] Add or update utility command tests for `review-to-findings`, `submit-feedback`, and `submit-action` native handling in `tests/test_python_wrappers.py` and `tests/test_native_runtime_boundary.py`

### Implementation for User Story 1

- [X] T010 [US1] Replace script-dispatch routing in `src/gh_address_cr/cli.py` with native supported-command routing and remove `COMMAND_TO_SCRIPT`, `SCRIPT_DIR`, and `run_script`
- [X] T011 [US1] Keep current internal helper implementations callable without `src/gh_address_cr/legacy_scripts/` and document any retained helper paths as internal in tests
- [X] T012 [US1] Remove `src/gh_address_cr/legacy_scripts/` and update `pyproject.toml` package-data expectations so the runtime package no longer carries script wrappers
- [X] T013 [US1] Verify `python3 -m gh_address_cr --help`, `python3 -m gh_address_cr review --help`, `python3 -m gh_address_cr review-to-findings --help`, `python3 -m gh_address_cr submit-feedback --help`, and `python3 -m gh_address_cr submit-action --help`

**Checkpoint**: User Story 1 proves supported workflows no longer rely on legacy script dispatch.

---

## Phase 4: User Story 2 - Reject Superseded Entrypoints Clearly (Priority: P2)

**Goal**: Superseded low-level command names fail loudly before side effects.

**Independent Test**: Unsupported historical commands return non-zero with migration guidance and no PR session files.

### Tests for User Story 2

- [X] T014 [P] [US2] Add unsupported legacy command assertions for representative low-level commands in `tests/test_runtime_packaging.py`
- [X] T015 [P] [US2] Add no-session-mutation assertions for unsupported historical commands in `tests/test_runtime_packaging.py`

### Implementation for User Story 2

- [X] T016 [US2] Implement explicit unsupported legacy command rejection and migration guidance in `src/gh_address_cr/cli.py`
- [X] T017 [US2] Update root help text in `src/gh_address_cr/cli.py` so removed low-level commands are absent and current supported workflows are named
- [X] T018 [US2] Verify `python3 -m gh_address_cr cr-loop --help`, `python3 -m gh_address_cr session-engine --help`, and `python3 -m gh_address_cr clean-state --help` fail with unsupported legacy guidance

**Checkpoint**: User Story 2 proves obsolete entrypoints fail fast and safely.

---

## Phase 5: User Story 3 - Preserve Historical Context Without Runtime Cost (Priority: P3)

**Goal**: Active guidance is clean while retained historical specs are marked archival or superseded.

**Independent Test**: Documentation tests pass and search results show no active runnable legacy-script instructions in current guidance.

### Tests for User Story 3

- [X] T019 [P] [US3] Add active guidance scan assertions for `skill/`, `README.md`, and generated plugin payload in `tests/test_skill_docs.py` and `tests/test_plugin_packaging.py`
- [X] T020 [P] [US3] Add historical artifact marker assertions for specs that retain removed skill script paths or runtime wrapper references in `tests/test_cli_skill_sync_artifacts.py`

### Implementation for User Story 3

- [X] T021 [US3] Update active guidance in `README.md`, `skill/SKILL.md`, `skill/agents/openai.yaml`, and `skill/references/` to remove runnable legacy-script instructions
- [X] T022 [US3] Mark retained historical compatibility references as superseded by 013 in older `specs/` artifacts that still mention removed script paths
- [X] T023 [US3] Rebuild or check `plugin/gh-address-cr/` payload with `scripts/build_plugin_payload.py --check` and update generated payload if needed

**Checkpoint**: User Story 3 proves historical context remains auditable without active runtime cost.

---

## Phase 6: Polish & Cross-Cutting Verification

**Purpose**: Complete the Spec Kit and superb verification gates.

- [X] T024 Run `ruff check src tests`
- [X] T025 Run `python3 -m unittest discover -s tests`
- [X] T026 Run `python3 -m gh_address_cr --help`
- [X] T027 Run `python3 -m gh_address_cr agent manifest`
- [X] T028 Run `scripts/build_plugin_payload.py --check`
- [X] T029 Run `git diff --check`
- [X] T030 Update `specs/013-remove-legacy-compat/quickstart.md` with final verification evidence summary
- [X] T031 Run `speckit-superb-verify` completion gate and archive evidence under `.specify/evidence/`

---

## Phase 7: Runtime Handler Removal

**Purpose**: Complete the historical-burden cleanup by deleting obsolete
low-level handler modules, removing handler-named runtime packages, and keeping
only current command modules that are part of the supported workflow surface.

- [X] T032 Add failing package contract tests that reject `src/gh_address_cr/legacy_handlers/`, `src/gh_address_cr/command_handlers/`, and obsolete handler-script dispatch in installed runtime payload inspection
- [X] T033 Delete obsolete low-level handler modules that are no longer part of the current supported workflow surface
- [X] T034 Move retained current helper implementations to `src/gh_address_cr/commands/` and update runtime subprocess calls to use `python -m gh_address_cr.commands.<module>`
- [X] T035 Update tests to exercise module invocation instead of direct legacy/helper script paths
- [X] T036 Re-run targeted runtime/package tests and affected workflow suites after removal
- [X] T037 Re-run full lint, unittest, CLI smoke, plugin payload check, diff check, and archive updated superb evidence

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup; blocks user story implementation.
- **US1 (Phase 3)**: Depends on Foundational; MVP.
- **US2 (Phase 4)**: Depends on US1 routing cleanup.
- **US3 (Phase 5)**: Can start after Foundational, but plugin payload check depends on active guidance updates.
- **Polish (Phase 6)**: Depends on selected user stories being complete.

### User Story Dependencies

- **US1**: Establishes current supported workflows without legacy script dispatcher.
- **US2**: Uses US1 routing cleanup to reject removed low-level commands explicitly.
- **US3**: Documents and verifies the current-versus-historical boundary.

### Parallel Opportunities

- T002 and T003 can run in parallel.
- T004 through T007 can run in parallel because they affect separate test files.
- T008 and T009 can run in parallel.
- T014 and T015 can run in parallel.
- T019 and T020 can run in parallel.
- Final verification commands must run after all implementation tasks.

## Implementation Strategy

### MVP First

1. Complete T001-T007 to establish RED tests.
2. Complete US1 (T008-T013) so supported workflows are native-only.
3. Validate US1 with targeted tests before changing rejection behavior.

### Incremental Delivery

1. Add explicit unsupported legacy rejection for US2.
2. Clean active guidance and historical markers for US3.
3. Run the full verification suite and superb completion gate.

### TDD Rule

For every behavior-changing task, write or update the failing test first, run it
to observe RED, then implement the minimum change to make it GREEN. Mark tasks
`[X]` only after fresh evidence exists.
