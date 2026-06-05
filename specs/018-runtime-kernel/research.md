# Research: Runtime Kernel

## Decision: Ship A Minimal GitHub Review-Thread Kernel Slice

**Rationale**: The feature goal is to stop review-resolution edge-case growth without rewriting every workflow path. A focused review-thread slice gives maintainers an independently verifiable boundary for facts, projection, policy, command planning, and execution evidence while leaving existing CLI behavior stable.

**Alternatives considered**:

- Full workflow rewrite: rejected because it would blur acceptance evidence and increase migration risk.
- Documentation-only architecture spec: rejected because the requested outcome requires executable determinism.
- Patching final-gate conditionals directly: rejected because it would repeat the plateau problem.

## Decision: Facts Are Versioned Runtime Inputs With Stable Logical Identity

**Rationale**: Review-thread observations and command execution results need stable identities so replay and reordering produce the same projection. The first slice uses explicit fact kinds and schema versions. Unsupported versions fail loudly.

**Alternatives considered**:

- Reusing artifact JSON files as implicit truth: rejected because artifacts are compatibility/reporting outputs unless modeled as event sources.
- Accepting arbitrary dictionaries in policy code: rejected because malformed facts would silently create branch-specific behavior.

## Decision: Projection Owns Stale, Reopened, Resolved, And Evidence-Pending Classification

**Rationale**: Stale/reopened/resolved ambiguity is the current source of scattered workflow branches. Projection must derive the current review work item state once, using deterministic ordering by logical observation time, sequence, and fact identity.

**Alternatives considered**:

- Letting final-gate recalculate unresolved work: rejected because it would duplicate projection logic.
- Treating stale threads as terminal: rejected because existing project contracts say stale/outdated threads are still unresolved until explicitly handled.

## Decision: Policy Uses One Decision Table Over Projection

**Rationale**: The kernel must produce exactly one next-state decision. The ordered policy table is: malformed or contradictory projection -> `blocked`; active local-action work -> `ready_for_action`; external dependency -> `waiting_for_external_input`; no blockers -> `final_gate_eligible`.

**Alternatives considered**:

- Returning multiple possible next actions: rejected because agents need stable Status-to-Action routing.
- Embedding command planning in policy: rejected because decisions and side effects must remain separable.

## Decision: Command Plans Are Idempotent And Non-Executing

**Rationale**: Planned side effects are an outbox boundary. They need stable logical IDs so retrying or regenerating a plan does not duplicate logical actions. Execution evidence is a separate fact kind.

**Alternatives considered**:

- Posting GitHub replies during policy evaluation: rejected because it mixes decision and side effect ownership.
- Counting a plan as completion evidence: rejected because completion requires recorded execution results.

## Decision: Reporting Writes Are Outside Completion Semantics

**Rationale**: Reporting overhead cannot include the reporting write itself without recursion. This slice defines reporting facts as diagnostics-only and excludes reporting writes from completion semantics.

**Alternatives considered**:

- Rewriting the report after measuring the report write: rejected because it creates a self-referential artifact.
- Letting telemetry reports satisfy review completion: rejected because telemetry is observed evidence, not review-resolution truth.
