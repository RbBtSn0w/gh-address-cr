# Tasks: Fix-All Thread Replies

**Input**: Design documents from `specs/014-fix-all-thread-replies/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required by spec FR-009 and FR-010. Write behavior tests before implementation for default addressing guidance, per-thread evidence preservation, fix-all rejection/shortcut behavior, and published reply body distinctness.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because the task touches different files and does not depend on incomplete tasks
- **[Story]**: Maps to user stories from spec.md
- All task descriptions include exact repository-relative file paths

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the current behavior and contract surfaces before changing runtime behavior.

- [X] T001 Capture the current generic `agent fix-all` same-file multi-thread behavior in notes inside specs/014-fix-all-thread-replies/quickstart.md
- [X] T002 [P] Inspect current runtime command hints and batch skeleton generation in src/gh_address_cr/cli.py
- [X] T003 [P] Inspect current batch evidence merge and fix-all acceptance paths in src/gh_address_cr/core/workflow.py
- [X] T004 [P] Inspect current published reply rendering assertions in tests/test_native_workflow.py and tests/test_control_plane_workflow.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define shared runtime helpers and contract expectations that all user stories rely on.

**Critical**: No user story implementation should begin until this phase is complete.

- [X] T005 Define generic shortcut rejection status, reason code, and next-action wording constants in src/gh_address_cr/core/workflow.py
- [X] T006 Define per-item fix-all evidence input parsing shape in src/gh_address_cr/cli.py and src/gh_address_cr/core/workflow.py
- [X] T007 Define homogeneous repeated concern fields and validation rules in src/gh_address_cr/core/workflow.py
- [X] T008 [P] Add shared same-file mixed-question session fixtures/helpers in tests/test_control_plane_workflow.py
- [X] T009 [P] Add shared fake GitHub reply body capture helper updates in tests/test_native_workflow.py

**Checkpoint**: Foundation ready; user story implementation can now proceed.

---

## Phase 3: User Story 1 - Address Threads One-To-One (Priority: P1)

**Goal**: Ordinary multi-thread PR addressing uses per-thread batch evidence, and mixed review questions publish distinct targeted replies.

**Independent Test**: Present two active review threads on the same file with different questions; verify default guidance points to the per-thread batch skeleton, accepted evidence preserves each item `summary` and `why`, and published replies differ with targeted rationale.

### Tests for User Story 1

- [X] T010 [P] [US1] Add failing test for default address guidance preferring per-thread batch skeleton over generic fix-all in tests/test_control_plane_workflow.py
- [X] T011 [P] [US1] Add failing test that common batch fix_reply summary does not overwrite item-specific summary and why in tests/test_control_plane_workflow.py
- [X] T012 [P] [US1] Add failing publish test proving two mixed review questions generate distinct targeted reply bodies in tests/test_native_workflow.py
- [X] T013 [P] [US1] Add failing documentation-contract test for per-thread batch guidance in tests/test_skill_docs.py

### Implementation for User Story 1

- [X] T014 [US1] Update default addressing instructions and command hints to prioritize `agent submit-batch` skeleton in src/gh_address_cr/cli.py
- [X] T015 [US1] Update batch response merge so item-specific summary and why override generic common fix_reply text in src/gh_address_cr/core/workflow.py
- [X] T016 [US1] Update publish body rendering or accepted response preparation to preserve per-thread rationale in src/gh_address_cr/core/workflow.py
- [X] T017 [US1] Update README default review-thread handling guidance in README.md
- [X] T018 [US1] Update skill default review-thread handling guidance in skill/SKILL.md
- [X] T019 [US1] Update Status-to-Action Map to make per-thread batch skeleton the ordinary path in skill/references/status-action-map.md
- [X] T020 [US1] Run focused US1 tests for tests/test_control_plane_workflow.py, tests/test_native_workflow.py, and tests/test_skill_docs.py with python3 -m unittest tests.test_control_plane_workflow tests.test_native_workflow tests.test_skill_docs

**Checkpoint**: User Story 1 is independently functional and testable.

---

## Phase 4: User Story 2 - Constrain Fix-All To Homogeneous Repeats (Priority: P2)

**Goal**: `agent fix-all` remains available only for explicit homogeneous repeated concerns or when per-item evidence is supplied.

**Independent Test**: Run `agent fix-all` on same-file mixed-question threads without per-item evidence and verify rejection; then verify per-item evidence and explicit homogeneous repeated nit paths both work without weakening leases or validation.

### Tests for User Story 2

- [X] T021 [P] [US2] Add failing test that mixed-question `agent fix-all` without per-item evidence rejects before publish_ready in tests/test_control_plane_workflow.py
- [X] T022 [P] [US2] Add failing test that `agent fix-all --input` preserves per-item summary and why for mixed threads in tests/test_control_plane_workflow.py
- [X] T023 [P] [US2] Add failing test that explicit homogeneous repeated-nit `agent fix-all` remains accepted with lease and validation evidence in tests/test_control_plane_workflow.py
- [X] T024 [P] [US2] Add failing wrapper/help test for new fix-all evidence and homogeneous shortcut flags in tests/test_python_wrappers.py
- [X] T025 [P] [US2] Add failing test that `agent fix-all --input` preserves per-item severity, severity_note, and validation evidence in tests/test_control_plane_workflow.py
- [X] T026 [P] [US2] Add failing test that generic `agent fix-all` rejects matched threads with missing or unreadable body unless per-item evidence is supplied in tests/test_control_plane_workflow.py
- [X] T027 [P] [US2] Add failing test that ordinary `agent fix-all` rejects or routes stale/outdated matched threads to the explicit stale-thread path in tests/test_control_plane_workflow.py

### Implementation for User Story 2

- [X] T028 [US2] Add `agent fix-all --input <batch-response.json>` CLI parsing and validation in src/gh_address_cr/cli.py
- [X] T029 [US2] Add explicit homogeneous shortcut options and required rationale validation in src/gh_address_cr/cli.py
- [X] T030 [US2] Route fix-all per-item evidence input through existing batch lease validation in src/gh_address_cr/core/workflow.py
- [X] T031 [US2] Reject generic fix-all for mixed, uncertain, missing-body, or stale/outdated thread sets before evidence acceptance in src/gh_address_cr/core/workflow.py
- [X] T032 [US2] Preserve per-item severity, severity_note, validation evidence, and homogeneous repeated concern rationale in accepted fix_reply evidence in src/gh_address_cr/core/workflow.py
- [X] T033 [US2] Update final-gate recovery command hints if generic fix-all is no longer a safe default in src/gh_address_cr/core/gate.py
- [X] T034 [US2] Run focused US2 tests for tests/test_control_plane_workflow.py and tests/test_python_wrappers.py with python3 -m unittest tests.test_control_plane_workflow tests.test_python_wrappers

**Checkpoint**: User Stories 1 and 2 both work independently.

---

## Phase 5: User Story 3 - Prevent Generic Reply Regression (Priority: P3)

**Goal**: Runtime, docs, skill guidance, and tests keep the one-to-one reply contract aligned so future changes cannot reintroduce generic repeated replies.

**Independent Test**: Compare public guidance, machine summaries, accepted evidence, and published reply artifacts for mixed review threads and confirm generic duplicate replies are rejected or absent.

### Tests for User Story 3

- [X] T035 [P] [US3] Add documentation-contract assertions for narrowed fix-all usage in tests/test_skill_docs.py
- [X] T036 [P] [US3] Add wrapper contract assertions for machine summary command hints in tests/test_python_wrappers.py
- [X] T037 [P] [US3] Add regression assertion that published mixed-question replies are non-identical and include item-specific rationale in tests/test_native_workflow.py

### Implementation for User Story 3

- [X] T038 [US3] Update agent protocol docs with per-thread batch default and narrowed fix-all contract in skill/references/agent-protocol.md
- [X] T039 [US3] Update OpenAI agent guidance with per-thread reply evidence requirements in skill/agents/openai.yaml
- [X] T040 [US3] Update runtime help text and command examples for narrowed fix-all usage in src/gh_address_cr/cli.py
- [X] T041 [US3] Update README public surface notes to distinguish shared fix evidence from per-thread reviewer-answer evidence in README.md
- [X] T042 [US3] Run focused US3 tests for tests/test_skill_docs.py, tests/test_python_wrappers.py, and tests/test_native_workflow.py with python3 -m unittest tests.test_skill_docs tests.test_python_wrappers tests.test_native_workflow

**Checkpoint**: All user stories are independently functional and covered by regression tests.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final contract consistency, full verification, and handoff readiness.

- [X] T043 [P] Verify repo-root versus skill-root path language in README.md, skill/SKILL.md, skill/references/agent-protocol.md, and skill/references/status-action-map.md
- [X] T044 [P] Verify quickstart scenarios remain aligned with implemented behavior in specs/014-fix-all-thread-replies/quickstart.md
- [X] T045 Run ruff check src tests for src/ and tests/ from repository root
- [X] T046 Run python3 -m unittest discover -s tests for tests/ from repository root
- [X] T047 Run python3 -m gh_address_cr --help for src/gh_address_cr/ from repository root
- [X] T048 Run git diff --check for repository-root changes in .
- [X] T049 For any real PR-session use of this feature, run gh-address-cr final-gate <owner/repo> <pr_number> and record the evidence in specs/014-fix-all-thread-replies/quickstart.md or the implementation handoff (N/A: no real PR-session was handled in this implementation run)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion; blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational; MVP scope.
- **User Story 2 (Phase 4)**: Depends on Foundational and should run after US1 if sharing reply-evidence merge behavior.
- **User Story 3 (Phase 5)**: Depends on US1 and US2 contract decisions.
- **Polish (Phase 6)**: Depends on all selected user stories.

### User Story Dependencies

- **US1 Address Threads One-To-One**: MVP; no dependency on US2 or US3 after Foundational.
- **US2 Constrain Fix-All To Homogeneous Repeats**: Can start after Foundational, but final implementation should reuse US1 per-thread evidence preservation.
- **US3 Prevent Generic Reply Regression**: Depends on US1 and US2 behavior so docs and wrapper tests match the final public contract.

### Within Each User Story

- Write the listed failing tests first.
- Implement runtime behavior after tests demonstrate the regression.
- Update docs and skill guidance in the same story phase when public behavior changes.
- Run the focused story tests before moving to the next story.

### Parallel Opportunities

- T002, T003, and T004 can run in parallel during setup.
- T008 and T009 can run in parallel after foundational constants are defined.
- US1 test tasks T010 through T013 can run in parallel.
- US2 test tasks T021 through T027 can run in parallel.
- US3 test tasks T035 through T037 can run in parallel.
- Polish checks T043 and T044 can run in parallel before full verification.

---

## Parallel Example: User Story 1

```bash
Task: "Add failing test for default address guidance preferring per-thread batch skeleton over generic fix-all in tests/test_control_plane_workflow.py"
Task: "Add failing test that common batch fix_reply summary does not overwrite item-specific summary and why in tests/test_control_plane_workflow.py"
Task: "Add failing publish test proving two mixed review questions generate distinct targeted reply bodies in tests/test_native_workflow.py"
Task: "Add failing documentation-contract test for per-thread batch guidance in tests/test_skill_docs.py"
```

---

## Parallel Example: User Story 2

```bash
Task: "Add failing test that mixed-question agent fix-all without per-item evidence rejects before publish_ready in tests/test_control_plane_workflow.py"
Task: "Add failing test that agent fix-all --input preserves per-item summary and why for mixed threads in tests/test_control_plane_workflow.py"
Task: "Add failing test that explicit homogeneous repeated-nit agent fix-all remains accepted with lease and validation evidence in tests/test_control_plane_workflow.py"
Task: "Add failing wrapper/help test for new fix-all evidence and homogeneous shortcut flags in tests/test_python_wrappers.py"
Task: "Add failing test that agent fix-all --input preserves per-item severity, severity_note, and validation evidence in tests/test_control_plane_workflow.py"
Task: "Add failing test that generic agent fix-all rejects matched threads with missing or unreadable body unless per-item evidence is supplied in tests/test_control_plane_workflow.py"
Task: "Add failing test that ordinary agent fix-all rejects or routes stale/outdated matched threads to the explicit stale-thread path in tests/test_control_plane_workflow.py"
```

---

## Parallel Example: User Story 3

```bash
Task: "Add documentation-contract assertions for narrowed fix-all usage in tests/test_skill_docs.py"
Task: "Add wrapper contract assertions for machine summary command hints in tests/test_python_wrappers.py"
Task: "Add regression assertion that published mixed-question replies are non-identical and include item-specific rationale in tests/test_native_workflow.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup and Foundational phases.
2. Complete US1 tests and implementation.
3. Validate that ordinary PR thread addressing uses the per-thread batch skeleton and publishes distinct targeted replies.
4. Stop and review before narrowing fix-all behavior.

### Incremental Delivery

1. US1 restores the default one-to-one reply path.
2. US2 narrows fix-all and adds per-item or homogeneous shortcut behavior.
3. US3 locks docs, machine hints, and regression coverage.
4. Polish runs full verification and records final-gate evidence for real PR-session use.

### Parallel Team Strategy

With multiple agents or developers:

1. Complete Setup and Foundational tasks together.
2. Assign US1 runtime behavior and publish tests to one worker.
3. Assign US2 fix-all CLI and workflow constraints to another worker after shared helper agreement.
4. Assign US3 docs and wrapper contracts after US1/US2 public wording stabilizes.

## Notes

- Public behavior changes must update runtime, docs, and executable tests together.
- Skill-owned docs use skill-root-relative paths; repo-root docs and tests use repo-root paths.
- Do not weaken lease ownership, validation evidence, reply evidence, or final-gate proof.
- Commit only when explicitly requested.
