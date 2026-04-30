---
description: "Task list for reply template parity implementation"
---

# Tasks: Reply Template Parity

**Input**: Design documents from `/specs/009-reply-template-parity/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: TDD approach. Write or update tests for every changed renderer, publish, and skill parity behavior before implementation.

**Organization**: Tasks are grouped by user story to keep each behavior independently testable.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the active feature context and baseline.

- [x] T001 Confirm `009-reply-template-parity` branch and `.specify/feature.json` point to `specs/009-reply-template-parity`
- [x] T002 Run baseline targeted tests for current reply rendering in `tests/test_native_workflow.py`, `tests/test_aux_scripts.py`, and `tests/test_skill_docs.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define the shared renderer contract before story work.

- [x] T003 Add shared runtime renderer contract tests in `tests/test_aux_scripts.py`
- [x] T004 Add skill asset parity tests in `tests/test_skill_docs.py`

**Checkpoint**: Foundation ready - user story implementation can now begin.

---

## Phase 3: User Story 1 - Template-Consistent Fix Replies (Priority: P1) MVP

**Goal**: Publish fix replies with v1 severity-specific template wording.

**Independent Test**: `agent publish` posts exact P1/P2/P3 style bodies and ignores raw `reply_markdown` for fix responses.

### Tests for User Story 1

- [x] T005 [US1] Update fix publish golden tests in `tests/test_native_workflow.py`
- [x] T006 [US1] Add runtime fix renderer tests for P1/P2/P3 in `tests/test_aux_scripts.py`

### Implementation for User Story 1

- [x] T007 [US1] Extend `src/gh_address_cr/core/reply_templates.py` with severity-specific fix rendering
- [x] T008 [US1] Keep `src/gh_address_cr/core/workflow.py` fix publish path using `fix_reply` evidence

---

## Phase 4: User Story 2 - Template-Consistent Clarify And Defer Replies (Priority: P2)

**Goal**: Publish clarify/defer replies through templates instead of raw markdown.

**Independent Test**: `agent publish` wraps accepted rationale in v1 clarify/defer template structure.

### Tests for User Story 2

- [x] T009 [US2] Add clarify/defer publish tests in `tests/test_native_workflow.py`
- [x] T010 [US2] Add missing `reply_markdown` fail-fast regression tests in `tests/test_native_workflow.py`

### Implementation for User Story 2

- [x] T011 [US2] Add clarify and defer renderers in `src/gh_address_cr/core/reply_templates.py`
- [x] T012 [US2] Update `src/gh_address_cr/core/workflow.py` to render clarify/defer bodies before GitHub side effects

---

## Phase 5: User Story 3 - Skill And Runtime Renderer Parity (Priority: P3)

**Goal**: Keep skill script and packaged template assets aligned with runtime output.

**Independent Test**: Script output and asset contract tests fail if templates drift.

### Tests for User Story 3

- [x] T013 [US3] Update `skill/scripts/generate_reply.py` behavior tests in `tests/test_aux_scripts.py`
- [x] T014 [US3] Add skill/runtime parity checks in `tests/test_skill_docs.py`

### Implementation for User Story 3

- [x] T015 [US3] Make `skill/scripts/generate_reply.py` and `src/gh_address_cr/legacy_scripts/generate_reply.py` reuse the runtime renderer
- [x] T016 [US3] Sync `skill/assets/reply-templates/*.md` with the runtime contract

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Complete Speckit and repository verification.

- [x] T017 Update README or skill references only if public wording needs clarification
- [x] T018 Mark completed tasks in `specs/009-reply-template-parity/tasks.md`
- [x] T019 Run `ruff check src tests`
- [x] T020 Run `/opt/homebrew/bin/pyenv exec python -m unittest discover -s tests`
- [x] T021 Run CLI smoke checks for `python -m gh_address_cr --help` and `skill/scripts/cli.py --help`
- [x] T022 Run `git diff --check`

## Dependencies & Execution Order

- Phase 1 before all implementation.
- Phase 2 before user stories.
- US1 before US2 only where shared `_publish_reply_body` behavior overlaps.
- US3 after runtime renderers are stable.
- Polish after all selected user stories pass.

## Implementation Strategy

1. Add failing tests for runtime publish and parity.
2. Implement the shared renderer and workflow integration.
3. Update skill script/assets to match runtime.
4. Run full verification and mark tasks complete.
