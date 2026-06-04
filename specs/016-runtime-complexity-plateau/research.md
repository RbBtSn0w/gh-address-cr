# Research: Runtime Complexity Plateau

## Decision: Use Phased Delivery Within One Spec Kit Feature

**Rationale**: The feature intentionally addresses a platform-level complexity plateau, but the implementation must not become a single broad rewrite. Three delivery slices keep the work independently valuable: handling boundary plus lease recovery first, telemetry boundary second, validation signals third.

**Alternatives considered**:

- Separate Spec Kit features for handler, lease, telemetry, and validation work. Rejected for this pass because the user asked for one platform spec and the boundaries interact through the same PR session lifecycle.
- One all-at-once refactor. Rejected because it would make verification hard and increase regression risk in public CLI behavior.

## Decision: Treat Work Item Handling as Runtime-Owned Boundaries, Not Skill Logic

**Rationale**: The constitution requires deterministic runtime ownership of state transitions and side effects. A handling boundary should declare applicability, required evidence, completion criteria, terminal failure reasons, and next actions. Skill guidance may explain how agents react, but must not decide handler selection.

**Alternatives considered**:

- Add more prompt guidance in `skill/SKILL.md`. Rejected because it would keep core behavior in prose and worsen drift.
- Keep expanding existing core branching. Rejected because it preserves the current complexity failure mode.

## Decision: Start With One High-Value Work Item Type

**Rationale**: Migrating all work item behavior at once is unnecessary and risky. A first slice must prove parity for one high-value type, expose the registration/selection contract, and leave unmigrated behavior unchanged.

**Alternatives considered**:

- Migrate all GitHub thread and local finding types at once. Rejected because it would widen scope beyond a safe planning slice.
- Only write an abstract contract with no migrated type. Rejected because it would not produce executable proof.

## Decision: Lease Recovery Outcomes Are Additive Machine-Readable Contract Fields

**Rationale**: Agent frustration comes from errors that are technically correct but not actionable. Recovery must distinguish `renew`, `reclaim`, `refresh_state`, `stop`, and `already_completed` so agents can recover without guessing.

**Alternatives considered**:

- Keep current `LeaseSubmissionError` reason codes only. Rejected because they do not always encode the safe next action.
- Automatically accept expired submissions during a broad grace period. Rejected because it risks overwriting newer runtime truth.

## Decision: Telemetry Must Stay Fail-Open For Core Review Flows With A 250ms Normal-Path Budget

**Rationale**: Telemetry is useful observed evidence, not completion authority. A concrete 250ms user-visible delay budget gives planning and testing an objective threshold. When telemetry cannot stay inside that budget, the runtime should emit reduced coverage diagnostics instead of blocking review resolution.

**Alternatives considered**:

- Block core review flows when telemetry fails. Rejected because it violates the telemetry evidence boundary.
- Make telemetry entirely best-effort and silent. Rejected because it hides report quality degradation and undermines audit trust.

## Decision: Logic Validation Is Advisory Except For False Completion Evidence

**Rationale**: The desired validator should catch evidence gaps and contradictions without becoming a second review engine. It may influence gate diagnostics or next actions, but only missing required evidence, state conflicts, or false completion contradictions should block completion.

**Alternatives considered**:

- AI-based second-pass review for every item. Rejected as too heavy and likely to slow routine workflows.
- Regex-only markers. Rejected because the spec explicitly targets hidden logical contradictions beyond marker text.

## Decision: Keep Public Skill Changes Narrow And Behavior-Oriented

**Rationale**: The packaged skill is a thin adapter. It may teach agents how to respond to new recovery outcomes, telemetry coverage labels, and validation signals, but all authoritative decisions must remain in the runtime.

**Alternatives considered**:

- Put handler routing instructions in skill references. Rejected because routing is runtime state behavior.
- Avoid skill updates entirely. Rejected because agent-facing new statuses would otherwise be unexplained.
