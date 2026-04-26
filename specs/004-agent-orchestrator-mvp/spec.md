# Feature Specification: Agent Orchestrator MVP

**Feature Branch**: `004-agent-orchestrator-mvp`  
**Created**: 2026-04-26  
**Status**: Draft  
**Input**: User description: "004-agent-orchestrator-mvp. 目标：PR-scoped 的多 agent 协调器 MVP。Runtime CLI 仍然是权威控制面；Orchestrator 只负责任务调度、租约领取、状态轮转、恢复；Worker Agent 只处理 ActionRequest；Publisher / Final Gate 仍由 runtime 执行；Skill 仍然只是 adapter。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deterministic Task Dispatch (Priority: P1)

As a maintainer, I want the orchestrator to read the current PR session status from the Runtime CLI and issue specialized `ActionRequest` packets to available agents, so that the correct role (triage, fixer, verifier) is assigned to the correct task.

**Why this priority**: This is the core coordination loop. Without deterministic dispatch, multi-agent work reverts to unmanaged parallel execution.

**Independent Test**: Can be tested by providing a session with one unclassified finding; the orchestrator must output an `ActionRequest` for the `triage` role and wait for a response.

**Acceptance Scenarios**:

1. **Given** a PR session with an open item, **When** `orchestrate step` is run, **Then** the system identifies the required role and generates a worker-compatible request.
2. **Given** a waiting state, **When** no agents are available for the required role, **Then** the orchestrator reports a wait state instead of proceeding blindly.

---

### User Story 2 - Lease-Based Conflict Prevention (Priority: P1)

As an agent in a multi-agent environment, I want the orchestrator to enforce claim leases on review items, so that I don't waste compute or cause state conflicts by working on an item already claimed by another agent.

**Why this priority**: Parallel execution safety is the primary reason for a formal coordinator.

**Independent Test**: Can be tested by attempting to claim an item that already has an active, unexpired lease in `session.json`; the orchestrator must reject the second claim.

**Acceptance Scenarios**:

1. **Given** an item with an active lease, **When** another agent attempts to claim it, **Then** the orchestrator returns a lease-conflict error.
2. **Given** an expired lease, **When** a new agent requests the item, **Then** the orchestrator allows the new claim after reclaiming the stale lease.

---

### User Story 3 - Resumable Session Recovery (Priority: P1)

As a DevOps engineer, I want the orchestrator to persist its internal coordination state in the PR workspace, so that I can resume a long-running review session after an interruption (e.g., CI timeout or network failure) without losing already-accepted evidence.

**Why this priority**: Reliability in CI/CD environments is non-negotiable.

**Independent Test**: Can be tested by interrupting the orchestrator after evidence is submitted but before publication, then running `orchestrate resume` and verifying the session picks up from the last saved state.

**Acceptance Scenarios**:

1. **Given** an interrupted session, **When** `orchestrate resume` is run, **Then** it loads the local PR workspace and validates the state of all active leases and pending responses.
2. **Given** a resume attempt, **If** the local PR workspace is missing or corrupted, **Then** the orchestrator fails loudly and requires a full refresh via Runtime CLI.

---

### User Story 4 - Parallel Work Stream Execution (Priority: P2)

As a maintainer with a large PR, I want the orchestrator to manage multiple independent work streams (items in different files) simultaneously, so that the overall review cycle time is reduced.

**Why this priority**: Efficiency gain is the secondary value of multi-agent orchestration.

**Independent Test**: Can be tested with a PR containing findings in `file_a.py` and `file_b.py`; the orchestrator must allow concurrent `ActionRequest` issuance for both items.

**Acceptance Scenarios**:

1. **Given** two items in non-conflicting files, **When** the orchestrator steps, **Then** it allows both to be in an active `FIXING` or `TRIAGE` state under separate leases.
2. **Given** items with overlapping file or context keys, **When** one is claimed, **Then** the other is blocked from parallel execution until the first lease is released.

### Edge Cases

- What happens when an agent submits an `ActionResponse` for a lease that just expired?
- How does the orchestrator handle a verifier rejecting the evidence provided by a fixer? (It MUST return the item to a blocked/fix-required state).
- What happens if the Runtime CLI version is incompatible with the Orchestrator MVP?
- How is "completion" defined if one agent passes final-gate but another still has an active lease? (Final-gate MUST be the terminal authority).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide high-level orchestration verbs: `start`, `status`, `step`, `resume`, and `stop`.
- **FR-002**: The Orchestrator MUST be a thin layer that delegates all state persistence, side effects (GitHub IO), and final-gate logic to the **Runtime CLI**.
- **FR-003**: System MUST identify the "next best action" by polling the Runtime CLI machine summary.
- **FR-004**: Orchestrator MUST issue `ActionRequest` packets and accept `ActionResponse` packets following the **Structured Agent Protocol**.
- **FR-005**: System MUST enforce **Claim Leases** (expiry, conflict detection, reclaiming) to prevent parallel mutation hazards.
- **FR-006**: The Orchestrator MUST track the `run_id` and maintain an audit log of coordination events (dispatches, claims, submissions, rejections).
- **FR-007**: System MUST support a **Deterministic Mode** where it does not automatically invoke LLMs but prepares worker packets for manual or external execution.
- **FR-008**: The Orchestrator MUST NOT bypass the **Final Gate** authority of the Runtime CLI.
- **FR-009**: System MUST allow for role-based filtering (e.g., "only step triage tasks").

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: The orchestrator is NOT a new control plane. It is a consumer of the Runtime CLI. All authoritative state remains in the PR-scoped session state managed by the runtime.
- **CLI / Agent Contract Impact**: Adds `agent orchestrate` (or similar) surface. MUST preserve all existing machine summary fields and reason codes.
- **Evidence Requirements**: Orchestrator MUST verify that an `ActionResponse` contains the required evidence defined in the `ActionRequest` before calling `agent submit` on the runtime.
- **Packaged Skill Boundary**: Orchestrator implementation belongs in the `src/` runtime package. The skill adapter remains a thin policy layer.
- **Fail-Fast Behavior**: MUST fail fast on lease conflicts, invalid response formats, or runtime errors.

### Key Entities

- **OrchestrationSession**: The volatile coordination state layered on top of the durable PR session.
- **WorkQueue**: The derived list of pending actions categorized by role and item.
- **WorkerPacket**: The bundle containing an `ActionRequest` and necessary context for a worker agent.
- **LeaseRegistry**: The component (backed by session state) that tracks active claims and expirations.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A single orchestrator instance can coordinate 3+ independent review items across 2+ distinct agent roles without state corruption.
- **SC-002**: Resuming an interrupted orchestration session takes less than 5 seconds (excluding IO) and restores 100% of accepted-but-not-published evidence.
- **SC-003**: 100% of GitHub side effects are executed through the Runtime CLI's serialized publishing path.
- **SC-004**: 0% of orchestration steps bypass the final-gate proof for completion claims.

## Assumptions

- The `ActionRequest` and `ActionResponse` schemas defined in Stage 5 are sufficient for the MVP.
- Worker agents are capable of reading the `WorkerPacket` and producing the required JSON response.
- The Runtime CLI's `session.json` and machine summary are the reliable source of truth for the orchestrator.
