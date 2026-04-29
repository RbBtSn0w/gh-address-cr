---
description: "Task list for Agent Orchestrator MVP implementation"
---

# Tasks: Agent Orchestrator MVP

**Input**: Design documents from `/specs/004-agent-orchestrator-mvp/`
**Prerequisites**: plan.md, spec.md, data-model.md, contracts/

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project structure and orchestration package initialization

- [x] T001 Create `orchestrator` package structure in `src/gh_address_cr/orchestrator/__init__.py`
- [x] T002 [P] Create initial test files in `tests/test_orchestrator_harness.py`, `tests/test_orchestrator_session.py`, and `tests/test_lease_scheduling.py`

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data models and CLI group setup required for all stories

- [x] T003 Implement `OrchestrationSession` and `LeaseRecord` data models in `src/gh_address_cr/orchestrator/session.py`
- [x] T004 Implement basic queue management data structures in `src/gh_address_cr/orchestrator/queue.py`
- [x] T005 [P] Register `agent orchestrate` command group and placeholders in `src/gh_address_cr/cli.py`
- [x] T006 Define orchestration state transitions (INITIALIZED, RUNNING, PAUSED, COMPLETED, FAILED) in `src/gh_address_cr/orchestrator/session.py`

## Phase 3: User Story 1 - Deterministic Task Dispatch (Priority: P1)

**Goal**: Read PR session status and issue specialized `ActionRequest` packets (`WorkerPacket`)

### Tests for User Story 1
- [x] T007 [P] [US1] Contract test for `WorkerPacket` generation schema in `tests/test_orchestrator_session.py`
- [x] T008 [P] [US1] Integration test for `orchestrate step` dispatching triage task in `tests/test_orchestrator_harness.py`

### Implementation for User Story 1
- [x] T009 [US1] Implement `WorkerPacket` data model and payload builder in `src/gh_address_cr/orchestrator/worker.py`
- [x] T010 [US1] Implement `agent orchestrate start` command to initialize queue in `src/gh_address_cr/orchestrator/harness.py`
- [x] T011 [US1] Implement `agent orchestrate step` command to poll runtime status and issue packet in `src/gh_address_cr/orchestrator/harness.py`
- [x] T012 [P] [US1] Add role-based filtering (`--role`) logic to `step` command in `src/gh_address_cr/orchestrator/harness.py`
- [x] T013 [P] [US1] Implement specific exit codes for zero pending items in `step` command in `src/gh_address_cr/cli.py`

## Phase 4: User Story 2 - Lease-Based Conflict Prevention (Priority: P1)

**Goal**: Enforce claim leases with TTL to prevent conflicts and reclaim expired leases

### Tests for User Story 2
- [x] T014 [P] [US2] Unit test for rejecting conflicting lease claims in `tests/test_lease_scheduling.py`
- [x] T015 [P] [US2] Unit test for reclaiming expired leases (TTL) in `tests/test_lease_scheduling.py`

### Implementation for User Story 2
- [x] T016 [US2] Implement lease TTL and expiration validation logic in `src/gh_address_cr/orchestrator/session.py`
- [x] T017 [US2] Integrate conflict detection and lease rejection (Fail Loud) in `step` flow in `src/gh_address_cr/orchestrator/harness.py`
- [x] T018 [US2] Implement explicit lease release logic (including verifier reject handling) in `src/gh_address_cr/orchestrator/session.py`
- [x] T019 [US2] Implement `agent orchestrate stop` to fail loud if active leases exist in `src/gh_address_cr/orchestrator/harness.py`

## Phase 5: User Story 3 - Resumable Session Recovery (Priority: P1)

**Goal**: Persist coordination state in PR workspace for safe resumption after interruptions

### Tests for User Story 3
- [x] T020 [P] [US3] Integration test for `orchestrate resume` restoring queue state in `tests/test_orchestrator_harness.py`
- [x] T021 [P] [US3] Error handling test for missing/corrupted `orchestration.json` in `tests/test_orchestrator_session.py`

### Implementation for User Story 3
- [x] T022 [US3] Implement `orchestration.json` IO persistence separated from `session.json` in `src/gh_address_cr/orchestrator/session.py`
- [x] T023 [US3] Implement `agent orchestrate resume` command to reload state and validate leases in `src/gh_address_cr/orchestrator/harness.py`
- [x] T024 [P] [US3] Add Fail Loud condition for missing `orchestration.json` during resume in `src/gh_address_cr/orchestrator/session.py`
- [x] T025 [P] [US3] Implement `agent orchestrate status` to print queue and active leases in `src/gh_address_cr/orchestrator/harness.py`

## Phase 6: User Story 4 - Parallel Work Stream Execution (Priority: P2)

**Goal**: Manage multiple independent work streams while blocking overlapping file access

### Tests for User Story 4
- [x] T026 [P] [US4] Test concurrent issuance for non-conflicting files in `tests/test_lease_scheduling.py`
- [x] T027 [P] [US4] Test parallel claim blocking for overlapping file keys in `tests/test_lease_scheduling.py`

### Implementation for User Story 4
- [x] T028 [US4] Implement file/context overlap detection logic in `src/gh_address_cr/orchestrator/queue.py`
- [x] T029 [US4] Update lease granting to block parallel access attempts on overlapping keys in `src/gh_address_cr/orchestrator/session.py`

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, robust retries, and comprehensive testing

- [x] T029a [P] Unit test for Bounded Retry enforcing max 3 attempts and outputting human handoff format in `tests/test_orchestrator_harness.py`
- [x] T029b [P] Unit test for `step` failing loudly when response path is empty or unwritten in `tests/test_orchestrator_harness.py`
- [x] T030 [P] Implement Bounded Retry + Fail Loud + Human Handoff logic for external agent parsing in `src/gh_address_cr/orchestrator/worker.py`
- [x] T031 [P] Integrate missing response handling (TTL fallback) in `src/gh_address_cr/orchestrator/harness.py`
- [x] T032 Verify no orchestration step bypasses final-gate proof in `tests/test_orchestrator_harness.py`
- [x] T033 Run `python3 -m unittest discover -s tests` to ensure all existing and new tests pass
- [x] T034 [P] Update `AGENTS.md` and repository README to document Orchestrator MVP public surfaceace pass
- [x] T034 [P] Update `AGENTS.md` and repository README to document Orchestrator MVP public surface