# Research: Orchestrator-Runtime Integration

## Decision: Queue Population from Core Session
**Decision**: `handle_start` and `handle_resume` will use `session_engine.load_session` to re-sync the volatile `queued_items`.
**Rationale**: `session.json` is the authoritative source. By filtering for `blocking: true` and `handled: false` items, we ensure the orchestrator never gets out of sync with the runtime's reality.
**Alternatives considered**: Manually passing IDs to `start`. Rejected as it's error-prone and doesn't handle interruptions well.

## Decision: WorkerPacket Composition
**Decision**: `handle_step` will invoke `workflow.issue_action_request` (which creates a lease in core state) and then wrap the resulting `ActionRequest` artifact into a `WorkerPacket`.
**Rationale**: This preserves the Stage 5 `ActionRequest` contract while allowing the orchestrator to inject the necessary coordination metadata (`run_id`, `lease_token`, `response_path`) required for its own lease management.
**Alternatives considered**: Modifying `ActionRequest` schema. Rejected as it violates architectural boundaries and core contract stability.

## Decision: Feedback Loop to Core Workflow
**Decision**: `handle_submit` will call `workflow.submit_action_response` after validating evidence.
**Rationale**: The orchestrator must not directly mutate the core session. By using the `workflow` API, we ensure that all state transitions (e.g., `OPEN` -> `FIXED`) are performed deterministically by the control plane.
**Alternatives considered**: Orchestrator writing directly to `session.json`. Rejected as a severe violation of Principle I (Control Plane Owns State).

## Decision: Authoritative Gating on Stop
**Decision**: `handle_stop` will execute the logic of `session_engine.cmd_gate` and check the return code.
**Rationale**: `cmd_gate` is the project's canonical verification method. Returning a non-zero exit code (2) if the gate fails ensures that `orchestrate stop` is a reliable signal for CI completion.
**Alternatives considered**: Orchestrator implementing its own check. Rejected as redundant and likely to drift from the core gate logic.

## Decision: Bounded Retry Implementation
**Decision**: Implement the bounded retry loop (MAX_RETRIES=3) within `handle_submit`. If parsing fails, it fails the command but keeps the lease. A future `submit` attempt increments the counter (persisted in `orchestration.json`).
**Rationale**: This prevents a broken worker from stalling the orchestrator indefinitely while giving transient IO issues a chance to resolve.
**Alternatives considered**: Internal loop in `harness`. Rejected because the orchestrator is a CLI tool; the retry state must be persisted across invocations.
