# Tasks: Orchestrator-Runtime Integration

**Feature Name**: Orchestrator-Runtime Integration
**Spec**: [specs/005-orchestrator-runtime-integration/spec.md]
**Plan**: [specs/005-orchestrator-runtime-integration/plan.md]

## Phase 1: Setup

- [X] T001 Initialize task tracking in `specs/005-orchestrator-runtime-integration/tasks.md`

## Phase 2: Foundational

- [X] T002 Update `OrchestrationSession` data model with `retry_counts` in `src/gh_address_cr/orchestrator/session.py`
- [X] T003 Ensure `session_engine.load_session` and `cmd_gate` are correctly exposed for orchestrator use in `src/gh_address_cr/orchestrator/harness.py`

## Phase 3: User Story 1 - Authoritative Task Dispatch (Priority: P1)

**Goal**: Populate queue from core session and use runtime for task selection.
**Independent Test**: `orchestrate start` followed by `step` issues a valid packet from real `session.json`.

- [X] T004 [US1] Implement core session item polling in `handle_start` in `src/gh_address_cr/orchestrator/harness.py`
- [X] T005 [US1] Implement runtime-driven task acquisition via `workflow.issue_action_request` in `handle_step` in `src/gh_address_cr/orchestrator/harness.py`
- [X] T006 [P] [US1] Create unit test for `handle_start` queue synchronization in `tests/test_orchestrator_harness.py`
- [X] T007 [P] [US1] Create integration test for `handle_step` using real `ActionRequest` artifact in `tests/test_orchestrator_harness.py`
- [X] T018 [US1] Add `status` verification: `orchestrate start` then `status` reports authoritative queue count from runtime state in `tests/test_orchestrator_harness.py`
- [X] T019 [US1] Add regression test for stale queue reconciliation: `handle_step` must re-sync from `session.json` before dispatch and skip stale item IDs.
- [X] T023 [US1] Add `resume`-to-`status` convergence test: `orchestrate resume` then immediate `status` must reflect `session.json` queue count and clear stale `queued_items`.
- [X] T024 [US1] Add `handle_step` safeguard test for missing workflow context (no eligible role context): return `WAITING`/`READY_FOR_FINAL_GATE` style terminal state without creating new core leases.

## Phase 4: User Story 2 - Authoritative State Feedback (Priority: P1)

**Goal**: Persist agent submissions back to core session.
**Independent Test**: `orchestrate submit` updates item status in `session.json`.

- [X] T008 [US2] Update `handle_submit` to call `workflow.submit_action_response` in `src/gh_address_cr/orchestrator/harness.py`
- [X] T009 [P] [US2] Create unit test for `handle_submit` calling runtime workflow in `tests/test_orchestrator_harness.py`
- [X] T010 [P] [US2] Verify lease release only occurs after successful runtime submission in `tests/test_lease_scheduling.py`
- [X] T020 [US2] Add regression test for race on submit: external session mutation during submit returns fast-fail (non-zero) and preserves lease for resume.

## Phase 5: User Story 3 - Authoritative Gating (Priority: P1)

**Goal**: Enforce final-gate on orchestrator stop.
**Independent Test**: `orchestrate stop` fails if PR items are unresolved.

- [X] T011 [US3] Integrate `session_engine.cmd_gate` check in `handle_stop` in `src/gh_address_cr/orchestrator/harness.py`
- [X] T012 [P] [US3] Create integration test for `handle_stop` failure on unresolved threads in `tests/test_orchestrator_harness.py`

## Phase 6: User Story 4 - Resilient Agent Communication (Priority: P2)

**Goal**: Implement bounded retry for response parsing.
**Independent Test**: System retries 3 times then raises `HumanHandoffRequired`.

- [X] T013 [US4] Implement bounded retry logic with persistence in `handle_submit` in `src/gh_address_cr/orchestrator/harness.py`
- [X] T014 [P] [US4] Create unit test for MAX_RETRIES enforcement in `tests/test_orchestrator_harness.py`
- [X] T021 [US4] Add test that retry_count is persisted in orchestration state and triggers `HumanHandoffRequired` exactly at 3 failed parse attempts.

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T015 Verify `WorkerPacket` schema compliance in `src/gh_address_cr/orchestrator/worker.py`
- [X] T025 Add execution-time guard for status/queue reconciliation path in `src/gh_address_cr/orchestrator/harness.py` and a dedicated unit test (`tests/test_orchestrator_harness.py`) to prove it stays within the `SC-004` "near-real-time" budget.
- [X] T016 Run full test suite `python3 -m unittest discover -s tests`
- [X] T017 Final manual smoke test of integrated `agent orchestrate` loop

## Phase 8: Completeness & Traceability

- [X] T022 Verify all FR/SC acceptance criteria and edge-case scenarios in `specs/005-orchestrator-runtime-integration/spec.md` are mapped to at least one task.

## Dependencies

- US1 is a prerequisite for US2 and US3.
- US4 can be implemented in parallel with US2.

## Implementation Strategy

1. Fix `start` and `step` first to get real data flowing (MVP).
2. Wire up `submit` to ensure work is recorded.
3. Add `stop` gating for safety.
4. Add `US4` retries for production robustness.
