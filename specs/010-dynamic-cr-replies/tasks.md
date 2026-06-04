# Tasks: Dynamic CR Replies & Severity Accuracy

> **Historical note:** Superseded by `specs/012-cli-skill-sync` for current
> skill execution guidance. `skill/scripts` and `scripts/cli.py` examples below
> describe the earlier shim-era contract and are not current runnable paths.
> Issue #80 also supersedes any `core/cr_loop.py` implementation-path mentions
> below; dynamic replies now live on native runtime paths.

**Input**: Design documents from `/specs/010-dynamic-cr-replies/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Include test tasks for every behavior, CLI contract, parser, session transition, GitHub side effect, final-gate rule, or packaged-skill contract changed by the feature.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Register P0 and P4 severities in `src/gh_address_cr/core/reply_templates.py`
- [X] T002 Update `SEVERITY_RISK_NOTES` for P0-P4 in `src/gh_address_cr/core/reply_templates.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Define the formal Severity & Tone Rubric in `skill/agents/openai.yaml`
- [X] T004 [P] Create `tests/core/test_reply_templates.py` with failing test cases for P0-P4 rendering and multi-paragraph rationale validation

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 2 - Accurate P0-P4 Severity Classification (Priority: P1) 🎯 MVP

**Goal**: Ensure the agent accurately assesses and the runtime accurately validates the P0-P4 scale.

**Independent Test**: Run `python3 -m unittest tests/core/test_reply_templates.py` and verify P0/P4 validation logic passes.

### Tests for User Story 2

- [X] T005 [P] [US2] Implement unit tests for severity validation logic in `tests/core/test_reply_templates.py`

### Implementation for User Story 2

- [X] T006 [P] [US2] Implement P0-P4 validation logic in `src/gh_address_cr/core/reply_templates.py`
- [X] T007 [US2] Update `normalize_fix_reply_severity` in `src/gh_address_cr/core/cr_loop.py` to support P0 and P4
- [X] T008 [US2] Add JSON schema validation for P0-P4 in `src/gh_address_cr/agent/responses.py`

**Checkpoint**: At this point, P0-P4 severity classification is functional and validated.

---

## Phase 4: User Story 1 - Dynamic, Context-Aware Code Review Replies (Priority: P1)

**Goal**: Enable "Structured but Rich" replies with multi-paragraph technical rationales and domain-specific references.

**Independent Test**: Use `generate_reply.py` to render a P0 reply with multiple paragraphs in the `why` field and verify markdown formatting.

### Tests for User Story 1

- [X] T009 [P] [US1] Add test cases for multi-paragraph rationale rendering in `tests/core/test_reply_templates.py`

### Implementation for User Story 1

- [X] T010 [P] [US1] Create `skill/assets/reply-templates/fixed-p0.md` with 🛑 emoji and rich structure
- [X] T011 [P] [US1] Create `skill/assets/reply-templates/fixed-p4.md` with 🔘 emoji and concise structure
- [X] T012 [P] [US1] Update `skill/assets/reply-templates/fixed-p1.md` (🔴), `fixed-p2.md` (🟠), and `fixed-p3.md` (🟡) to support multi-line rationale blocks
- [X] T013 [US1] Refactor `fix_reply` in `src/gh_address_cr/core/reply_templates.py` to handle multi-line `why` strings and enforce the 2-paragraph rule for P0/P1
- [X] T014 [US1] Update `clarify_reply` and `defer_reply` in `src/gh_address_cr/core/reply_templates.py` to support rich, context-aware rationales

**Checkpoint**: At this point, User Story 1 is functional, enabling rich and dynamic replies.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [X] T015 [P] Update `skill/references/agent-protocol.md` with the new P0-P4 scale and Rich Reply requirements
- [X] T016 Update `skill/references/mode-producer-matrix.md` if necessary
- [X] T017 Run all unit tests: `python3 -m unittest discover -s tests`
- [X] T018 Run `ruff check src tests`
- [X] T019 Verify CLI smoke checks: `python3 skill/scripts/generate_reply.py --help`
- [X] T020 [P] Update `CHANGELOG.md` with the new severity scale and dynamic reply feature

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup.
- **User Stories (Phases 3 & 4)**: Depend on Foundational. US1 and US2 can be implemented in parallel, but US2 is recommended first as it provides the classification truth.
- **Polish (Final Phase)**: Depends on all user stories.

---

## Implementation Strategy

### MVP First (P0-P4 + Rich Replies)

1. Complete Setup and Foundational phases.
2. Implement US2 (Accuracy) to establish the P0-P4 scale.
3. Implement US1 (Dynamism) to enable rich replies.
4. Validate with `quickstart.md` scenarios.

---

## Notes

- [P] tasks can be executed in parallel.
- [USx] labels ensure traceability to the feature specification.
- Ensure `src/gh_address_cr/core/reply_templates.py` remains the single source of truth for rendering logic.
