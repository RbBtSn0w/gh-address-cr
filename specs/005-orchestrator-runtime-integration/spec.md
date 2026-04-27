# Feature Specification: Orchestrator-Runtime Integration

**Feature Branch**: `005-orchestrator-runtime-integration`
**Created**: 2026-04-27  
**Status**: Draft  
**Input**: User description: "Fixing 004 Orchestrator gaps. Goal: Transform the skeleton orchestrator into a fully integrated coordinator that drives the Runtime CLI control plane. This includes real task dispatching via workflow.py, authoritative state feedback through submit_action_response, and enforcing final-gate during stop. It must also implement real bounded retry logic for worker responses and bind WorkerPacket to real runtime context."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Authoritative Task Dispatch (Priority: P1)

As a maintainer, I want the orchestrator to populate its queue from the actual PR session and use the runtime's internal logic to decide the next action, so that the orchestration is always in sync with the authoritative state.

**Why this priority**: This is the fundamental requirement for the orchestrator to be more than a mock. Without it, the orchestrator cannot manage real work.

**Independent Test**: Can be tested by starting an orchestration on a PR with known unclassified findings; the orchestrator's `status` must show the correct number of queued items, and `step` must issue a `WorkerPacket` matching a real finding from the session.

**Acceptance Scenarios**:

1. **Given** a PR session with 3 open local findings, **When** `orchestrate start` is run, **Then** the `orchestration.json` queue is populated with these 3 item IDs.
2. **Given** an orchestration has started, **When** `orchestrate status` is run, **Then** `queued_items` reported by the CLI equals the authoritative item count pulled from `session.json`.
3. **Given** a pending task, **When** `orchestrate step` is run, **Then** it calls `workflow.issue_action_request` and generates a `WorkerPacket` containing the runtime-vended request details.

---

### User Story 2 - Authoritative State Feedback (Priority: P1)

As an agent, I want my submissions to the orchestrator to be persisted back to the core PR session, so that my work actually resolves findings and progresses the review.

**Why this priority**: Without feedback into the core session, the orchestrator is a "write-only" loop that never completes the review.

**Independent Test**: Can be tested by submitting a valid `ActionResponse` to `orchestrate submit`; the `session.json` of the PR must show the item status changed from `OPEN` to `FIXED` (or the appropriate state).

**Acceptance Scenarios**:

1. **Given** an active lease for a finding, **When** `orchestrate submit` is run with a valid response, **Then** `workflow.submit_action_response` is called and the core session is updated.
2. **Given** an invalid response submission, **When** `orchestrate submit` is run, **Then** the core session is NOT updated, and the orchestrator lease is NOT released.

---

### User Story 3 - Authoritative Gating (Priority: P1)

As a DevOps engineer, I want the orchestrator to prevent a "clean stop" if the PR review is not actually complete according to the runtime's gatekeeper, so that I don't accidentally merge an incomplete review.

**Why this priority**: Ensures the orchestrator respects the project's safety contracts.

**Independent Test**: Can be tested by calling `orchestrate stop` on a PR with unresolved threads; the command must return a non-zero exit code and report that the final gate failed.

**Acceptance Scenarios**:

1. **Given** a PR with unresolved items, **When** `orchestrate stop` is run, **Then** it reports failure and returns exit code 2.
2. **Given** a PR where all items are resolved and published, **When** `orchestrate stop` is run, **Then** it returns exit code 0.

---

### User Story 4 - Resilient Agent Communication (Priority: P2)

As a system, I want to robustly handle transient failures when parsing agent responses, but fail loudly if a worker is consistently broken, so that I don't get stuck in an infinite loop or silent failure.

**Why this priority**: Operational stability in multi-agent environments.

**Independent Test**: Can be tested by providing a malformed JSON response file to `submit`; the system must retry parsing up to 3 times total, and eventually raise `HumanHandoffRequired` if invalid JSON persists.

**Acceptance Scenarios**:

1. **Given** a response file is temporarily unreadable or transiently invalid, **When** the submit flow is retried, **Then** parsing is attempted up to 3 times (persisted by orchestration state across invocations) before moving to human handoff.
2. **Given** a response file that is consistently invalid JSON, **When** the submit flow is attempted 3 times, **Then** it fails with `HumanHandoffRequired` and requires operator intervention.

### Edge Cases

- **Race Condition on Submit**: What happens if the core session is updated externally while the orchestrator is processing a submission? (Orchestrator should fail fast and require a `resume` or state refresh).
- **Inconsistent Queue**: If the core session shows 0 items but the orchestrator queue has 1, `step` must reconcile from runtime truth and should not issue packets from stale queue entries.
- **Missing Workflow Context**: If the requested role has no matching runtime context, `step` must return `READY_FOR_FINAL_GATE` or a clear role-specific `WAITING` state without dispatching unsafe work.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `handle_start` MUST call `session_engine.load_session` and populate the `queued_items` with IDs of all `blocking` and `unhandled` items.
- **FR-002**: `handle_step` MUST delegate task acquisition to `workflow.issue_action_request`.
- **FR-003**: `handle_submit` MUST call `workflow.submit_action_response` after local evidence verification.
- **FR-004**: `handle_stop` MUST execute the `session_engine.cmd_gate` logic to verify session completion.
- **FR-005**: `WorkerPacket` MUST be constructed using real metadata from the `ActionRequest` vended by the runtime.
- **FR-006**: The system MUST implement a loop-aware bounded retry mechanism for `parse_and_validate_response` with `MAX_RETRIES = 3`, persisting retry_count in orchestration state.
- **FR-007**: `handle_step` MUST re-verify the queue status from `session.json` before issuing any new packet.
- **FR-008**: `handle_resume` and `handle_status` MUST refresh the orchestration view from runtime state, and queue counts shown by `status` must remain within 1 second of runtime reality after resume.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Confirms the Runtime CLI as the authoritative owner of session state. Orchestration state is explicitly volatile and subservient to `session.json`.
- **CLI / Agent Contract Impact**: Extends the `agent orchestrate` group with real side-effects on the core session. Preserves all existing `WorkflowError` handling and machine summary reason codes.
- **Evidence Requirements**: Enforces that all `ActionResponse` payloads pass through `workflow.submit_action_response` for authoritative logging and state transition.
- **Packaged Skill Boundary**: Changes are concentrated in `src/gh_address_cr/orchestrator/` to keep the core runtime logic intact but reachable.
- **External Intake Replaceability**: Maintains the normalized findings contract by letting the runtime handle findings status.
- **Fail-Fast Behavior**: Fails loudly if runtime integration fails, if `final-gate` is bypassed, or if agent responses are consistently malformed.

### Key Entities *(include if feature involves data)*

- **OrchestrationSession**: Now acts as a synchronized shadow of the core `Session`, managing only the active worker leases and the volatile dispatch order.
- **WorkerPacket**: A wrapper for the Runtime's `ActionRequest`, adding orchestration metadata (`run_id`, `lease_token`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of task dispatches in `orchestrate step` are backed by a real `ActionRequest` artifact generated by the runtime.
- **SC-002**: 100% of successful `orchestrate submit` calls result in a corresponding state change in `session.json`.
- **SC-003**: `orchestrate stop` returns exit code 2 if there is at least one unresolved blocking item in the core session.
- **SC-004**: `orchestrate resume` then immediate `status` must report the same blocking/unhandled queue count as `session.json` within 1 second in normal execution.

## Assumptions

- The `SessionManager` in `core/session.py` is available and provides thread-safe or process-safe read/write via its existing locking mechanisms.
- `workflow.py` methods handle all GitHub IO and persistent state updates correctly as long as they are called with valid inputs.
- The `orchestration.json` file remains the owner of "who is working on what" (leases), while `session.json` remains the owner of "what needs to be done" and "what is already done".
