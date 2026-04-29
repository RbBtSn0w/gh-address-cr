# Feature Specification: Orchestrator Product Safety & Convergence

**Feature Branch**: `006-orchestrator-product-safety`
**Created**: 2026-04-27
**Status**: Verified
**Input**: Transforming Orchestrator 005 into an AI-safe deliverable product. Focusing on Status-to-Action map convergence, policy-only skill layer, and coordination guardrails.

## Clarifications

### Session 2026-04-27
- Q: Coordination Guardrails (FR-004) parameters location? → A: Safe defaults hardcoded in control plane, overrides via CLI/env persist into orchestration.json to prevent resume drift.
- Q: Human Intervention (FR-002) recovery path? → A: No override flags. Visible state in orchestration.json; manual fix then normal `submit` with same token to clear state.
- Q: Verified Lock (FR-006) mechanism? → A: Use orchestration.json as a coordination lock (completed: true). Core session remains untouched. If core has new items, clear lock and proceed.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Signal-Driven Control (Priority: P1)

As an AI runner, I want all exceptions and warnings to be surfaced as machine-readable reason codes within the `Status-to-Action` contract, so that I can make deterministic branching decisions (retry, stop, or handoff) without parsing stderr or "guessing" the state.

**Why this priority**: Essential for safety. Prevents AI from hallucinating success when transient or systemic failures occur.

**Independent Test**: Run `orchestrate submit` with a corrupted payload. Verify the output JSON contains a specific `reason_code` (e.g., `PAYLOAD_CORRUPT`) and a `next_action` (e.g., `RETRY` or `HUMAN_INTERVENTION`).

---

### User Story 2 - Policy-Only Skill Interaction (Priority: P1)

As a system maintainer, I want the `SKILL.md` instructions to explicitly forbid agents from inferring state from prose, forcing them to use only the provided machine summary, so that the agent's behavior remains consistent across different LLM versions.

**Why this priority**: Enforces the "Thin Skill" and "Behavioral Policy Layer" principles of the constitution.

**Independent Test**: Inspection of `SKILL.md` and verification that an agent following those instructions correctly handles a `WAITING_FOR_LEASES` status without attempting a `step`.

---

### User Story 3 - Coordination Guardrails (Priority: P2)

As a DevOps engineer, I want the orchestrator to have built-in safety limits (max concurrency, circuit breaking after N retries, role-based visibility), so that the fleet of agents doesn't consume excessive resources or enter an infinite loop.

**Why this priority**: Operational stability and cost control.

**Independent Test**: Mock a worker that always fails. Verify the orchestrator hits a circuit breaker (max retries) and enters a `FAILED` state requiring human resume.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: **Status-to-Action Convergence**: The `agent orchestrate` command group MUST return a structured JSON summary where `warning` and `error` conditions are mapped to valid `Status-to-Action` signals.
- **FR-002**: **Human Intervention Protocol**: Introduce an explicit `HUMAN_INTERVENTION_REQUIRED` status. State MUST be persisted in `orchestration.json` (e.g., `waiting_for_human: true`, `handoff_reason`, `artifact_path`). Recovery MUST occur via manual artifact repair followed by a normal `submit` (with original `--item-id` and `--token`), which clears the human intervention state upon success.
- **FR-003**: **Policy Enforcement**: Update `gh-address-cr/SKILL.md` to define the authoritative relationship between machine summary reason codes and agent branching logic.
- **FR-004**: **Coordination Guardrails**: Implement safe hardcoded defaults for `max_concurrency` and `circuit_breaker_threshold` in the control plane. Allow dynamic runner overrides (CLI args or ENV vars) which MUST be written to `orchestration.json` (e.g., `session.config`) to prevent drift upon resume.
- **FR-005**: **Role-Based Visibility**: Ensure `orchestrate step` only dispatches tasks to workers whose `role` matches the available runtime context (Status-to-Action mapping).
- **FR-006**: **Verified Lock**: Implement an Orchestration Completion Lock in `orchestration.json` (e.g., `completed: true`). `start` and `step` commands MUST evaluate this lock against the core `session.json` truth: if locked and core is complete, return `SESSION_LOCKED` (no-op). If core has new blocking/unhandled items, automatically clear the lock and proceed safely.

### Constitution Alignment *(mandatory)*

- **CLI Is The Stable Public Interface**: Directly enhances Principle II by solidifying the Status-to-Action Map.
- **Packaged Skill Boundary**: Solidifies Principle IV by converging `SKILL.md` into a pure Behavioral Policy Layer.
- **Fail-Fast Behavior**: Principle V is satisfied by turning "bypassed warnings" into "blocking signals".

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of non-zero exit paths in `agent orchestrate` produce a JSON output with a `reason_code` from the documented map.
- **SC-002**: `SKILL.md` size is reduced or focused such that 100% of branching instructions are based on machine reason codes.
- **SC-003**: Circuit breaker successfully stops orchestration after 3 consecutive worker failures (Configurable).

## Assumptions

- The `orchestration_audit.log` already captures sufficient raw data; this feature is about promoting that data to the control plane.
- The downstream AI/runner can parse JSON from stdout/file reliably.
