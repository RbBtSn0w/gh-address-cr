# Feature Specification: Evidence-Gated Runtime Consolidation

**Feature Branch**: `024-runtime-consolidation`  
**Created**: 2026-06-30  
**Status**: Draft  
**Input**: User description: "Define a safe, reversible implementation contract for issue #173 runtime consolidation, using the evaluation evidence from feature 023 before removing compatibility paths or changing public defaults."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Declare One Authority Per Runtime State Axis (Priority: P1)

As a maintainer, I want each review-resolution state axis to have one explicit authority and one derived compatibility projection, so that consolidation reduces state space instead of adding another workflow layer.

**Why this priority**: Duplicate ownership of review items, leases, checks, side effects, telemetry evidence, or final-gate eligibility can produce false completion and unrecoverable drift.

**Independent Test**: Replay representative runtime facts through current and candidate paths and verify that supported scenarios produce equivalent projections, policy decisions, command plans, and final-gate eligibility from one declared authority.

**Acceptance Scenarios**:

1. **Given** a supported review-resolution scenario, **When** its state ownership is inspected, **Then** each affected state axis has exactly one authoritative owner and any compatibility output is explicitly derived.
2. **Given** current and candidate paths disagree, **When** parity is evaluated, **Then** rollout stops until the difference is corrected or introduced through a documented, versioned contract change.
3. **Given** both legacy and kernel paths attempt to own the same transition, **When** the conflict is detected, **Then** the runtime fails loudly rather than selecting an implicit fallback.

---

### User Story 2 - Migrate Through Reversible Slices (Priority: P1)

As a maintainer, I want consolidation delivered as bounded migration slices with replay, shadow comparison, and rollback boundaries, so that legacy paths are removed only after their replacement is proven.

**Why this priority**: Removing workflow surfaces in one rewrite would combine state migration, public-contract change, and performance optimization into one unsafe decision.

**Independent Test**: Enable one migration slice for its supported cohort, exercise success and failure cases, then disable it and verify that runtime truth and archived evidence remain valid.

**Acceptance Scenarios**:

1. **Given** a proposed migration slice, **When** it enters planning, **Then** it names the affected state axes, replacement projection and policy, side-effect boundary, compatibility contract, parity proof, rollout cohort, and rollback trigger.
2. **Given** parity, contract, or replay evidence is incomplete, **When** removal is requested, **Then** the legacy path remains available and non-authoritative migration work cannot advance to deletion.
3. **Given** a rollout trigger is breached, **When** the slice is disabled, **Then** the previous supported path can resume without rewriting runtime facts or treating reporting artifacts as truth.

---

### User Story 3 - Accept Optimizations Only With Evaluation Evidence (Priority: P2)

As an engineer, I want truncation, command-session, and workflow-surface optimizations evaluated as independent hypotheses, so that token or latency improvements cannot justify worse review outcomes or forced compatibility loss.

**Why this priority**: These proposals have different risks and rollback boundaries. Bundling them would make regressions difficult to attribute and reverse.

**Independent Test**: Run a candidate optimization against the feature 023 supported cohort and verify it advances only when quality guardrails hold and the intended cost dimension improves with sufficient evidence.

**Acceptance Scenarios**:

1. **Given** a candidate optimization with supported feature 023 comparison evidence, **When** provisional and durable outcome guardrails hold and the target cost improves, **Then** it may advance to the next declared rollout stage.
2. **Given** `INSUFFICIENT_EVIDENCE` or a quality regression, **When** rollout is reviewed, **Then** the optimization remains non-default or is rolled back.
3. **Given** command-session mode is unavailable or unhealthy, **When** a supported review flow executes, **Then** a safe non-session path remains available until session mode independently satisfies its acceptance gate.

### Program Boundaries And Order

1. **Authority and parity**: Declare state ownership and prove candidate projections, decisions, and command plans against supported current behavior.
2. **Migration slices**: Move one state axis or workflow responsibility at a time behind explicit enablement and rollback boundaries.
3. **Optimization hypotheses**: Evaluate output truncation, command-session adoption, and workflow-surface deletion separately using feature 023.
4. **Contract cleanup**: Remove deprecated public or compatibility surfaces only after replacement behavior is documented, tested, versioned where necessary, and accepted by evidence.

### Edge Cases

- A partial migration must state which axes are kernel-authoritative and which remain owned by the current path.
- A candidate path that writes a side effect during projection or policy evaluation fails the slice contract.
- A shadow comparison must not execute duplicate GitHub side effects.
- Rollback must not discard valid runtime facts or require archived reports to reconstruct truth.
- A lower-cost candidate with unknown durable outcomes cannot become the default.
- Unsupported hosts and PR cohorts remain on the established supported path.
- Reporting or telemetry failure remains visible but cannot change review completion truth.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST define one authoritative owner for every migrated state axis, including review-item state, lease state, check state, side-effect execution evidence, telemetry evidence state, and final-gate eligibility.
- **FR-002**: System MUST model consolidation as bounded migration slices rather than one unbounded rewrite.
- **FR-003**: Every migration slice MUST identify external facts, authoritative projection, deterministic policy, side-effect command boundary, compatibility projection, replay coverage, supported cohort, and rollback trigger.
- **FR-004**: System MUST NOT remove a legacy path until its replacement projection, policy, side-effect boundary, recovery behavior, and executable contract tests exist.
- **FR-005**: System MUST detect ambiguous or duplicate state ownership and fail loudly.
- **FR-006**: System MUST keep runtime facts and recorded execution results authoritative over sessions, artifacts, telemetry, evaluation reports, and summaries.
- **FR-007**: System MUST compare current and candidate behavior without allowing shadow evaluation to perform duplicate external side effects.
- **FR-008**: System MUST block rollout when supported parity differences are unexplained or unversioned.
- **FR-009**: System MUST preserve or explicitly version public CLI behavior, machine-readable summaries, reason codes, wait states, and structured agent contracts before changing them.
- **FR-010**: System MUST keep output truncation, command-session adoption, and workflow-surface removal as independent rollout hypotheses with independent acceptance and rollback decisions.
- **FR-011**: System MUST preserve a supported non-session execution path until command-session mode satisfies operational-health, compatibility, recovery, and outcome gates.
- **FR-012**: System MUST NOT make lossy output truncation the default until supported evidence shows quality guardrails hold and the public output contract is preserved or versioned.
- **FR-013**: System MUST consume feature 023 comparison results without allowing evaluation output to become runtime truth or final-gate evidence.
- **FR-014**: System MUST treat `INSUFFICIENT_EVIDENCE`, unknown durable outcomes, or regressed quality guardrails as blockers for default rollout and legacy deletion.
- **FR-015**: Every risky optimization MUST declare its expected benefit, protected outcome guardrails, cohort rules, staged enablement, stop condition, and rollback action.
- **FR-016**: System MUST make rollback possible without rewriting authoritative facts, losing execution evidence, or relying on reporting artifacts for recovery.
- **FR-017**: System MUST deprecate duplicate models, compatibility shims, and telemetry fields only through an explicit inventory and documented contract boundary.
- **FR-018**: System MUST remove obsolete code, tests, docs, and skill guidance together when a deprecation gate is satisfied.
- **FR-019**: System MUST expose which state axes and workflow surfaces are migrated for every partially consolidated runtime version.
- **FR-020**: System MUST stop architecture work and revise the spec when a slice adds hidden fallbacks, artifact-backed truth, duplicate decision surfaces, or new state flags that do not reduce ambiguity.

### Migration Slice Acceptance Gate

A migration slice may become the default only when all applicable conditions hold:

- Authority ownership and derived compatibility boundaries are explicit.
- Deterministic replay and parity contracts pass for the supported cohort.
- Side-effect plans are idempotent and no shadow path can execute duplicates.
- Public behavior is preserved or explicitly versioned with tests and documentation.
- Recovery and rollback have executable coverage.
- Feature 023 reports sufficient evidence for the declared outcome and cost guardrails.
- Provisional and durable quality do not regress for the supported cohort.
- Operational-health regressions remain below the slice's declared stop threshold.

Provisional evidence alone may support shadowing or limited opt-in rollout, but not default rollout or irreversible removal. Legacy deletion additionally requires the replacement contract to have completed its declared deprecation window.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Runtime projection, policy, command planning, execution evidence, final-gate, leases, checks, sessions, telemetry attribution, and GitHub side effects are in scope and require Architecture Preflight per slice.
- **Runtime Kernel Model**: External facts feed one authoritative projection. Deterministic policy selects status and next action. Side effects are emitted as idempotent command plans and become evidence only through recorded execution results.
- **CLI / Agent Contract Impact**: Public commands and structured agent behavior remain stable unless an explicit version boundary updates code, tests, docs, and skill guidance together.
- **Evidence Requirements**: Runtime completion remains based on runtime facts and execution evidence. Feature 023 evaluates outcomes after the fact and cannot satisfy completion.
- **Packaged Skill Boundary**: Repo-root runtime owns migration and decisions. `skill/` remains a thin adapter to machine-readable next actions and documented diagnostics.
- **External Intake Replaceability**: Findings and review producers remain replaceable through normalized, versioned inputs.
- **Telemetry Evidence Boundary**: Telemetry observes cost and health but does not own review state. Missing optional telemetry can limit rollout evidence without blocking review completion.
- **Architecture Plateau Risk**: Each slice must reduce duplicate ownership or decision surfaces. New fallback branches without state-space reduction invalidate the slice.
- **Fail-Fast Behavior**: Ambiguous ownership, malformed facts, inconsistent execution references, unsafe contract changes, and unsupported rollout claims fail loudly.

### Key Entities *(include if feature involves data)*

- **Runtime Authority Map**: One owner and derived-output boundary for each state axis.
- **Migration Slice**: A reversible unit of authority transfer with parity, rollout, and rollback contracts.
- **Compatibility Projection**: A derived representation that preserves supported consumers without owning truth.
- **Parity Observation**: A side-effect-free comparison of current and candidate projections, decisions, and plans.
- **Optimization Hypothesis**: One proposed cost or complexity improvement with independent guardrails.
- **Rollout Gate**: Deterministic conditions controlling shadow, opt-in, default, deprecation, and deletion stages.
- **Rollback Trigger**: A measured parity, quality, economics, or operational-health condition requiring a stage reversal.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every state axis touched by a slice has exactly one authoritative owner and one documented compatibility direction.
- **SC-002**: Replaying supported facts produces deterministic candidate projections, policy decisions, and command plans.
- **SC-003**: Shadow comparison performs zero external GitHub side effects.
- **SC-004**: An unexplained parity difference, `INSUFFICIENT_EVIDENCE`, or quality regression blocks default rollout.
- **SC-005**: Every enabled slice can be disabled without rewriting authoritative facts or losing valid execution evidence.
- **SC-006**: Unsupported cohorts continue using an established supported path during partial migration.
- **SC-007**: Output truncation, command-session adoption, and workflow-surface removal can each be accepted, rejected, or rolled back independently.
- **SC-008**: No legacy path is deleted using provisional outcome evidence alone.
- **SC-009**: Public-contract changes update executable tests, documentation, and packaged-skill guidance in the same versioned change.
- **SC-010**: Completed slices reduce duplicate state owners or decision surfaces without introducing hidden fallback branches.

## Non-Goals

- Replacing all runtime, workflow, session, telemetry, and final-gate code in one migration.
- Making command-session mode the only supported execution path in the first rollout.
- Making lossy thread-context truncation the default before evidence and contract gates pass.
- Letting evaluation reports, archives, or telemetry become authoritative runtime state.
- Removing every compatibility path merely because an internal replacement exists.
- Expanding the runtime kernel into a review producer or vendor-specific host integration.

## Assumptions

- Issue `#173` is the primary product requirement for this feature.
- Feature `023-runtime-eval-foundation` lands enough supported evaluation semantics before any irreversible cleanup in this feature.
- Existing `018-runtime-kernel` projection, policy, and command-plan boundaries are the intended authority foundation; this feature governs adoption and consolidation rather than replacing that architecture.
- Initial slices prefer additive parity observations and derived compatibility projections over destructive migration.
- Durable-verification evidence may arrive later than provisional evidence, so rollout stages distinguish reversible experiments from irreversible deletion.
