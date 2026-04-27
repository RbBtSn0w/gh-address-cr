# Tasks: Orchestrator Product Safety & Convergence

**Feature Name**: Orchestrator Product Safety & Convergence
**Spec**: [specs/006-orchestrator-product-safety/spec.md]
**Plan**: [specs/006-orchestrator-product-safety/plan.md]

## Phase 1: Setup

- [ ] T001 Initialize task tracking in `specs/006-orchestrator-product-safety/tasks.md`

## Phase 2: Foundational

- [ ] T002 Update `OrchestrationSession` and lease data model fields (`config`, `completed`, `waiting_for_human`, `handoff_reason`, `artifact_path`) in `src/gh_address_cr/orchestrator/session.py`
- [ ] T003 Ensure CLI output handlers support structured `reason_code` and `next_action` fields in `src/gh_address_cr/orchestrator/harness.py`

## Phase 3: User Story 1 - Signal-Driven Control (Priority: P1)

**Goal**: Exceptions and warnings are surfaced as machine-readable reason codes within the `Status-to-Action` contract.
**Independent Test**: Run `orchestrate submit` with a corrupted payload. Verify the output JSON contains a specific `reason_code` (e.g., `PAYLOAD_CORRUPT`) and a `next_action` (e.g., `RETRY` or `HANDOFF`).

- [ ] T004 [US1] Inject `reason_code` and `next_action` mapping in `handle_submit`, `handle_step`, and `handle_start` exit paths in `src/gh_address_cr/orchestrator/harness.py`
- [ ] T005 [P] [US1] Create unit tests verifying structured error outputs and next actions in `tests/test_orchestrator_harness.py`

## Phase 4: User Story 3 - Coordination Guardrails (Priority: P2)

**Goal**: Implement safety limits (max concurrency, circuit breaking, role-based visibility) and verified session locking.
**Independent Test**: Mock a worker that always fails. Verify the orchestrator hits a circuit breaker (max retries) and enters a `FAILED` state requiring human resume. Verify lock works after clean stop.

- [ ] T006 [US3] Parse CLI args and ENV vars for `max_concurrency` and `circuit_breaker_threshold` and persist to `config` in `src/gh_address_cr/orchestrator/harness.py`
- [ ] T007 [US3] Enforce `max_concurrency` limit during task dispatch in `handle_step` in `src/gh_address_cr/orchestrator/harness.py`
- [ ] T008 [US3] Implement Role-Based Visibility filtering in `handle_step` in `src/gh_address_cr/orchestrator/harness.py`
- [ ] T009 [US3] Implement circuit breaker logic mapping N retries to `HUMAN_INTERVENTION_REQUIRED` state in `handle_submit` in `src/gh_address_cr/orchestrator/harness.py`
- [ ] T010 [US3] Implement manual repair recovery path clearing `waiting_for_human` state upon valid `submit` in `src/gh_address_cr/orchestrator/harness.py`
- [ ] T011 [US3] Implement Orchestration Completion Lock logic (`completed: true`) in `handle_stop` in `src/gh_address_cr/orchestrator/harness.py`
- [ ] T012 [US3] Implement lock evaluation and auto-clear logic against core truth in `handle_start` and `handle_step` in `src/gh_address_cr/orchestrator/harness.py`
- [ ] T013 [P] [US3] Create comprehensive unit tests for coordination guardrails, human intervention, and locking in `tests/test_orchestrator_harness.py`

## Phase 5: User Story 2 - Policy-Only Skill Interaction (Priority: P1)

**Goal**: Update skill instructions to explicitly forbid agents from inferring state from prose.
**Independent Test**: Inspection of `SKILL.md` to ensure branching is strictly based on `reason_code` and `next_action`.

- [ ] T014 [US2] Rewrite Orchestrator section in `gh-address-cr/SKILL.md` to mandate Status-to-Action map branches

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T015 Run full test suite `python3 -m unittest discover -s tests`
- [ ] T016 Final manual smoke test of integrated `agent orchestrate` guardrails
- [ ] T017 Verify performance goal: assert status/lock resolution overhead remains <100ms in `tests/test_orchestrator_harness.py`

## Dependencies

- Foundational tasks must be completed before any US phase.
- US1 (Signal-Driven Control) is foundational for US3's circuit breaker and locking signals.
- US3 must be completed before US2 to ensure the actual code emits the signals that `SKILL.md` will document.

## Implementation Strategy

1. Extend the data model first.
2. Implement the core signal reporting mechanism (US1) so failures are deterministic.
3. Build the complex guardrails (US3) on top of the signal mechanism.
4. Finally, update the agent-facing documentation (US2) to match the new strict reality.