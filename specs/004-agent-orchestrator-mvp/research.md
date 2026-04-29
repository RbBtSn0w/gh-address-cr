# Phase 0: Research

## Unknown: Coordinator Harness Integration
**Decision**: Add a new `agent orchestrate` command group in the CLI.
**Rationale**: Keeps the orchestration surface distinct from the primary `review` entrypoint to avoid expanding the default public surface prematurely, aligning with the MVP goal.
**Alternatives considered**: Integrating directly into `review`, which risks destabilizing the core pipeline before the orchestration logic matures.

## Unknown: Worker Packet Structure
**Decision**: The `WorkerPacket` will wrap the existing `ActionRequest` and include the `orchestration_run_id`, active `lease_token`, and paths for submitting the `ActionResponse`.
**Rationale**: Allows agents to process standard requests while the orchestrator tracks the volatile coordination metadata required for resuming and conflict detection.
**Alternatives considered**: Modifying the `ActionRequest` schema directly, which would violate the Stage 5 contract stability.

## Unknown: Orchestration Session State
**Decision**: Store volatile orchestration state (like active queues and claim tokens) in an `orchestration.json` artifact within the PR workspace, separate from `session.json`.
**Rationale**: Keeps the core PR `session.json` pure and managed solely by the Runtime CLI, while the orchestrator can persist its own restart logic safely.
**Alternatives considered**: Embedding queues directly into `session.json`, violating the strict separation between deterministic control plane and orchestration scheduling.
