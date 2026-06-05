# Data Model: Runtime Complexity Plateau

## WorkItemHandlingBoundary

Represents the runtime-owned handling contract for a supported work item type.

**Fields**:

- `boundary_id`: Stable identifier for the handling boundary.
- `item_kinds`: Work item kinds the boundary may handle.
- `applicability`: Conditions that must be true before the boundary can claim an item.
- `priority`: Deterministic selection priority when more than one boundary matches.
- `required_evidence`: Evidence required before the item can be accepted.
- `completion_criteria`: Conditions required before publish, resolve, or final gate can treat the item as handled.
- `terminal_failure_reasons`: Machine-readable reasons for unsupported or unsafe handling.
- `next_actions`: Agent-safe actions exposed when handling cannot continue.

**Validation Rules**:

- Exactly one boundary may own a work item after deterministic priority is applied.
- Boundary conflicts without deterministic priority fail fast.
- A boundary cannot weaken classification, reply, resolve, validation, or final-gate evidence requirements.

## LeaseRecoveryState

Represents the runtime decision after an agent submits, renews, or reclaims work around lease expiration.

**Fields**:

- `lease_id`: Lease being evaluated.
- `item_id`: Work item associated with the lease.
- `agent_id`: Agent attempting recovery.
- `request_id`: Request context that produced the response.
- `request_hash`: Stable request hash used to reject stale context.
- `lease_status`: Current lease status.
- `item_state`: Current work item state from runtime truth.
- `recovery_outcome`: One of `renew`, `reclaim`, `refresh_state`, `stop`, or `already_completed`.
- `reason_code`: Machine-readable reason for the outcome.
- `resume_command`: Safe command or instruction for the agent when applicable.

**State Transitions**:

- `active` -> `submitted` -> `accepted`
- `active` -> `expired` -> `reclaim` when item remains eligible
- `active` or `expired` -> `stop` when item has new owner, changed state, or false context
- Any state -> `already_completed` when runtime truth shows completion

**Validation Rules**:

- Expired submissions cannot overwrite changed runtime truth.
- Reclaim requires item eligibility and matching safe context.
- Recovery output must include a machine-readable next action or a terminal stop reason.

## TelemetryCoverageState

Represents the observed workflow evidence available for a PR session.

**Fields**:

- `coverage_label`: `complete`, `partial`, `runtime-only`, or `unavailable`.
- `sources`: Runtime, host-agent, generic-agent, or other accepted telemetry sources.
- `write_status`: `available`, `slow`, `failed`, `rejected`, or `unavailable`.
- `diagnostics`: Public-safe diagnostics for rejected or degraded telemetry.
- `privacy_status`: Whether sensitive content was accepted, sanitized, rejected, or absent.
- `report_path`: Structured report location when available.
- `overhead_ms`: User-visible overhead for telemetry work when measurable.

**Validation Rules**:

- Telemetry cannot mutate work item completion state.
- Core review flows remain fail-open when telemetry is missing, damaged, or slow.
- Telemetry-specific commands fail loudly for malformed, unsafe, unsupported, or ambiguous telemetry.
- Normal telemetry overhead should remain within 250ms per core workflow command.

## LogicValidationSignal

Represents a lightweight risk signal about agent evidence, state, or completion claims.

**Fields**:

- `signal_id`: Stable identifier for the signal instance.
- `item_id`: Work item being evaluated.
- `signal_type`: Evidence gap, state contradiction, unsupported completion claim, high-risk reply inconsistency, or low-confidence advisory.
- `confidence`: `high`, `medium`, or `low`.
- `explanation`: Public-safe explanation of the risk.
- `recommended_action`: Supplement evidence, reclassify, defer, refresh state, request human review, or continue.
- `gate_effect`: `advisory` or `blocking`.

**Validation Rules**:

- Signals are advisory by default.
- Signals become blocking only when they expose false completion evidence, missing required evidence, or runtime state contradiction.
- A signal cannot replace review production, classification, reply, resolve, or final-gate proof.

## DeliverySlice

Represents an independently verifiable implementation phase within this feature.

**Fields**:

- `slice_id`: Stable phase identifier.
- `scope`: User-visible capability delivered by the slice.
- `included_contracts`: Contracts changed by the slice.
- `acceptance_evidence`: Tests, CLI scenarios, or documentation checks proving the slice.
- `remaining_scope`: Explicitly deferred work.

**Validation Rules**:

- Each slice must produce user-visible value and executable evidence.
- Later slices cannot silently redefine earlier public outcomes.
- Unmigrated behavior remains compatible unless explicitly versioned.
