# Feature Specification: Runtime Kernel

**Feature Branch**: `018-runtime-kernel`  
**Created**: 2026-06-05  
**Status**: In Review
**Input**: User description: "Create a Runtime Kernel feature for gh-address-cr that stops unbounded review-resolution edge-case growth."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Project Review State From Facts (Priority: P1)

A maintainer or coding agent can provide the current GitHub review-thread facts for a pull request review session and receive one deterministic projected review state that identifies active work items, terminal items, stale items, reopened items, pending evidence, and final-gate blockers.

**Why this priority**: This is the minimal independently verifiable kernel slice. Without a single projection, later policy and side-effect planning would continue to depend on scattered workflow branches.

**Independent Test**: Can be fully tested by replaying the same review-thread fact set multiple times and verifying that the projected work-item state is byte-for-byte equivalent and contains the expected active, terminal, stale, and reopened items.

**Acceptance Scenarios**:

1. **Given** a pull request session with unresolved review threads, **When** those thread facts are projected, **Then** every unresolved actionable thread appears as an active work item with stable identity and source evidence.
2. **Given** the same set of thread facts in a different input order, **When** the facts are projected, **Then** the projection is identical to the original projection.
3. **Given** a previously resolved thread is later reopened, **When** the reopened fact is included, **Then** the projection marks the item active again and records the prior terminal state as historical context rather than completion truth.

---

### User Story 2 - Decide The Next Runtime Action (Priority: P2)

A maintainer or coding agent can ask the runtime kernel what should happen next for the projected review state and receive one deterministic decision: blocked, ready for action, waiting for external input, or eligible for final-gate.

**Why this priority**: The kernel must replace ad hoc final-gate and workflow-condition branching with explicit policy rules over the projection.

**Independent Test**: Can be fully tested by passing known projections into the policy decision step and verifying the same projection always produces the same decision and reason set.

**Acceptance Scenarios**:

1. **Given** a projection with required unresolved review work, **When** policy is evaluated, **Then** final-gate is not eligible and the decision identifies the blocking work.
2. **Given** a projection with no active review-thread work and no pending evidence, **When** policy is evaluated, **Then** the decision is eligible for final-gate.
3. **Given** a projection that depends on a reviewer or external producer response, **When** policy is evaluated, **Then** the decision is waiting for external input rather than ready for local action.

---

### User Story 3 - Plan Side Effects Without Performing Them (Priority: P3)

A maintainer or coding agent can obtain a command plan for required replies, resolves, retries, or final-gate checks without the decision path directly performing GitHub or artifact side effects.

**Why this priority**: Side effects must be separated from decisions so planned commands are auditable, idempotent, retryable, and only become trusted completion evidence after execution results are recorded.

**Independent Test**: Can be fully tested by generating command plans from projections and decisions, verifying stable idempotency keys, and proving that pending plans do not count as completion evidence until execution results are ingested.

**Acceptance Scenarios**:

1. **Given** a decision that is ready for action on an unresolved thread, **When** a command plan is produced, **Then** the plan contains the required reply or resolve command with a stable idempotency key and no direct side effect has occurred.
2. **Given** a planned reply command has not recorded an execution result, **When** completion is evaluated, **Then** the item remains incomplete.
3. **Given** a command execution result records a successful reply or resolve for the planned command, **When** the result is included as runtime evidence, **Then** completion semantics may use that result as trusted evidence.

### Edge Cases

- Duplicate or differently ordered thread facts must not produce different projected states.
- An already-resolved thread must not become active unless a later reopened fact exists.
- A stale thread must change projection and policy through documented state, not hidden workflow branches.
- A failed or missing side-effect execution result must leave the related completion requirement unresolved.
- Telemetry and reporting artifact writes must not create recursive completion requirements.
- Existing session or artifact files must not become authoritative truth unless explicitly modeled as versioned runtime event sources.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST represent GitHub review-thread inputs as typed runtime facts or events with stable identity, source, observed status, and observation time.
- **FR-002**: System MUST derive current PR review work from a single projection model rather than from scattered workflow-specific conditionals.
- **FR-003**: System MUST classify projected review-thread work into active, terminal, stale, reopened, waiting, and evidence-pending states using deterministic rules.
- **FR-004**: System MUST produce one deterministic policy decision for a projected state: blocked, ready for action, waiting for external input, or eligible for final-gate.
- **FR-005**: System MUST prevent final-gate eligibility whenever required unresolved review-thread work or required execution evidence remains.
- **FR-006**: System MUST produce side-effect command plans without directly performing side effects inside projection or policy evaluation.
- **FR-007**: System MUST give planned side effects stable idempotency identity so regenerating a plan for the same state does not create duplicate logical actions.
- **FR-008**: System MUST treat planned commands as incomplete until a corresponding execution result is recorded as runtime evidence.
- **FR-009**: System MUST keep existing public CLI behavior and structured agent protocol contracts stable during this kernel slice unless an additive, documented, tested contract is introduced.
- **FR-010**: System MUST preserve existing session and artifact compatibility while ensuring those files are not authoritative truth unless modeled as versioned event sources with executable contract tests.
- **FR-011**: System MUST separate telemetry and reporting semantics from runtime completion semantics.
- **FR-012**: System MUST define a non-self-referential reporting boundary when reporting overhead cannot include the reporting write itself without recursion.
- **FR-013**: System MUST include acceptance coverage proving determinism of projections, determinism of decisions, idempotency of command plans, final-gate blocking with unresolved work, and predictable stale/reopened/already-resolved thread handling.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature affects session state interpretation, GitHub review-thread facts, side-effect planning, artifact truth, telemetry boundaries, and final-gate eligibility. The deterministic runtime kernel is the owner of projection, policy, command planning, and completion evidence.
- **Runtime Kernel Model**: External inputs are typed review-thread facts and command execution-result facts. Projection derives review-thread work items. Policy maps projections to blocked, ready-for-action, waiting-for-external-input, or final-gate-eligible decisions. Command planning emits planned side effects and final-gate checks. Execution evidence enters as recorded facts. Artifacts and telemetry are reporting evidence unless explicitly versioned as event sources.
- **CLI / Agent Contract Impact**: Existing public commands, slash command identity, structured agent protocol schemas, reason-code semantics, and Status-to-Action Map behavior must remain stable. Any new kernel output is additive and covered by tests.
- **Evidence Requirements**: Review-thread completion requires projected terminal state plus recorded execution evidence for required reply or resolve side effects. Final-gate eligibility requires no active unresolved review work and no pending execution evidence.
- **Packaged Skill Boundary**: Runtime implementation and tests belong under repository-root source and test files. Skill-owned documents may describe the migration contract later, but the skill remains a thin behavioral adapter and does not own kernel logic.
- **External Intake Replaceability**: The feature preserves the normalized findings and review-producer boundary. The kernel slice consumes review-thread facts and does not couple behavior to a specific review producer.
- **Telemetry Evidence Boundary**: Telemetry reports coverage, overhead, diagnostics, and confidence. Telemetry artifact writes do not create review completion requirements. Reporting overhead excludes the reporting write itself unless a separate non-self-referential evidence artifact is introduced.
- **Architecture Plateau Risk**: This feature exists to reduce state space by introducing projection and policy boundaries. Adding scattered conditionals, hidden fallbacks, or artifact-backed truth would violate the feature goal.
- **Fail-Fast Behavior**: Malformed facts, unsupported fact versions, ambiguous thread identities, invalid command-plan inputs, and inconsistent execution-result references must fail loudly in the kernel slice.

### Key Entities *(include if feature involves data)*

- **Runtime Fact**: An observed external input or recorded action result, including review-thread status, source identity, observation time, and version.
- **Review Work Item**: A projected unit of review-resolution work derived from one or more facts.
- **Projection**: The current deterministic review state for a PR session derived from runtime facts.
- **Policy Decision**: The deterministic next-state decision and reason set produced from a projection.
- **Command Plan**: An idempotent plan of side-effect commands to execute outside the decision path.
- **Execution Evidence**: A recorded result of a planned command that may become trusted completion evidence.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Replaying the same review-thread facts at least three times produces identical projected state and policy decision.
- **SC-002**: Reordering the same input facts produces identical projected state and policy decision.
- **SC-003**: A projection containing unresolved required review-thread work always prevents final-gate eligibility.
- **SC-004**: Regenerating a command plan for the same projection and decision produces the same logical commands and idempotency keys.
- **SC-005**: Adding a stale, reopened, or already-resolved thread changes the projected state and decision only through documented projection and policy rules.
- **SC-006**: Telemetry/reporting artifact writes do not create recursive completion blockers or satisfy review-thread completion by themselves.

## Assumptions

- The first implementation slice is limited to GitHub review-thread handling and does not replace every existing workflow path.
- Existing public CLI commands remain available and keep their current user-facing behavior during adoption.
- Existing session and artifact files may continue to support compatibility and reporting, but the new kernel slice treats typed facts and recorded execution results as the modeled truth boundary.
- Full migration of leases, findings, checks, pending reviews, and telemetry ingestion into the kernel is future work unless needed to validate the review-thread slice.
