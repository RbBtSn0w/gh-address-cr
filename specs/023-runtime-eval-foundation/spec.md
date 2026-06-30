# Feature Specification: Read-Only Evaluation Plane

**Feature Branch**: `023-runtime-eval-foundation`  
**Created**: 2026-06-30  
**Status**: Verified
**Input**: User description: "Define a trustworthy evaluation plane for issue #174 so maintainers can determine whether review-resolution changes improve verified outcomes, token use, elapsed time, and operational reliability without changing runtime truth."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Evaluate Review Outcomes With Hybrid Verification (Priority: P1)

As a maintainer, I want review concerns evaluated with explicit provisional and durable verification states, so that current-cycle completion is useful without being confused with evidence that a concern stayed resolved.

**Why this priority**: A reply, resolve action, and passing final gate prove current-cycle completion but do not prove that a reviewer will not reopen the concern. Treating both claims as one outcome would overstate quality.

**Independent Test**: Evaluate an archived PR session containing classification, reply, resolve, final-gate, and later review observations, then verify that each concern receives the correct provisional and durable state with source attribution.

**Acceptance Scenarios**:

1. **Given** a concern with verified classification, durable reply evidence, required resolve and publish evidence, and a passing final gate, **When** it is evaluated before a later observation window completes, **Then** it is reported as `provisionally_verified` and not `durably_verified`.
2. **Given** a provisionally verified concern with a supported later observation and no reopen or equivalent recurrence, **When** it is evaluated, **Then** it is reported as `durably_verified` with the observation source and boundary.
3. **Given** a concern that is reopened or recurs equivalently after provisional verification, **When** it is evaluated, **Then** durable verification is denied and the negative outcome remains attributable to the original concern.

---

### User Story 2 - Compare Quality And Cost Without False Precision (Priority: P1)

As an engineer assessing a runtime or workflow change, I want comparison reports that separate outcome quality, workflow economics, and operational health, so that lower token use or latency cannot hide worse review outcomes.

**Why this priority**: Current telemetry can describe command health and coverage, but it does not reliably prove that a change resolves review concerns more effectively or cheaply.

**Independent Test**: Compare two matched cohorts with complete evidence and one unmatched or incomplete cohort, then verify that the supported comparison reports separate dimensions while the unsupported comparison returns `INSUFFICIENT_EVIDENCE`.

**Acceptance Scenarios**:

1. **Given** matched cohorts with required workflow, timing, token, and outcome evidence, **When** the evaluator compares them, **Then** quality, cost, and operational-health results are reported independently.
2. **Given** missing required coverage, insufficient sample size, or unmatched complexity, **When** a comparison is requested, **Then** it returns `INSUFFICIENT_EVIDENCE` and identifies the unsupported dimensions.
3. **Given** lower token use but worse reopen, recurrence, manual-recovery, or final-gate stability, **When** the result is summarized, **Then** the evaluator does not report the candidate as an improvement.

---

### User Story 3 - Preserve Runtime And Privacy Boundaries (Priority: P2)

As an operator, I want evaluation to consume privacy-safe archived evidence without becoming a runtime authority, so that measurement cannot mutate review state, satisfy final-gate, or expose sensitive host data.

**Why this priority**: Evaluation is only trustworthy when its source boundary and inability to affect completion are explicit.

**Independent Test**: Feed archived evidence containing supported observations, missing host telemetry, malformed records, and unsafe fields, then verify read-only behavior, explicit degraded coverage, fail-loud validation, and privacy filtering.

**Acceptance Scenarios**:

1. **Given** valid archived runtime evidence, **When** evaluation records are derived, **Then** the records preserve source attribution and cannot change runtime projection, policy, side effects, or final-gate eligibility.
2. **Given** host token telemetry is absent, **When** the run is evaluated, **Then** review resolution remains unaffected and token-based conclusions are explicitly unsupported.
3. **Given** malformed or unsafe evaluation input, **When** ingestion is attempted, **Then** it fails with an actionable diagnostic rather than silently accepting or rewriting the input.

### Verification Semantics

- **Provisionally Verified**: A concern has a verified current-cycle classification, durable reply evidence, required resolve and publish evidence, and a passing final gate, with no known contradictory runtime fact at evaluation time.
- **Durably Verified**: A provisionally verified concern also has a supported later observation showing no reopen or equivalent recurrence within the declared observation boundary.
- **Negative Durable Outcome**: A later reopen, equivalent recurrence, manual recovery, or final-gate regression linked to the concern prevents durable verification.
- Provisional and durable verification MUST be reported separately. A missing later observation is an unknown durable outcome, not a success or failure.

### First Supported Cohort

- The first supported workflow is the normal GitHub review-thread path through classification, reply, resolve when required, publish, and final-gate.
- Initial comparisons are limited to runs with stable PR and concern identity, runtime-version attribution, and required dimensional coverage.
- The first supported durable observation is a later GitHub reviewer round observed after provisional verification and correlated to the same PR at the same or a later head revision. Elapsed time, PR closure, or merge without that observation is insufficient.
- Token conclusions are limited to supported agent hosts that provide attributable token evidence; unsupported hosts may still produce non-token evaluation dimensions.
- Initial cohort matching MUST account for review-item count, changed-file count, diff size, and classification mix. Language/toolchain and required-check duration MUST also be included when they materially affect the measured workflow and supported evidence exists.
- Older or partial archives may be projected for diagnostics but MUST NOT be promoted into supported comparisons without the required evidence.

### Edge Cases

- A later review event that cannot be correlated to an earlier concern remains unlinked and cannot grant or deny durable verification for that concern.
- A merged or closed PR without a supported later review observation does not automatically grant durable verification.
- Multiple commands that overlap in time must not be double-counted in active wall time; summed resource time remains a separate measure.
- Duplicate observations must not increase sample size or outcome counts.
- Reporting artifacts that disagree with runtime evidence surface a diagnostic; runtime evidence remains authoritative.
- Telemetry and archive writes must not recursively require their own timing or completion evidence.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST introduce a read-only evaluation plane that derives per-concern, per-run, per-PR, and per-runtime-version records from archived authoritative evidence.
- **FR-002**: System MUST ensure evaluation records and reports can never mutate review state, plan or perform side effects, satisfy final-gate, or replace reply and resolve evidence.
- **FR-003**: System MUST represent `provisionally_verified`, `durably_verified`, unknown durable outcome, and negative durable outcome as distinct evaluation states.
- **FR-004**: System MUST require verified classification, durable reply evidence, required resolve and publish evidence, and passing final-gate evidence before assigning `provisionally_verified`.
- **FR-005**: System MUST require a declared supported later-observation boundary with no reopen or equivalent recurrence before assigning `durably_verified`.
- **FR-006**: System MUST preserve the source, observation time, correlation identity, and evidence boundary used for each verification state.
- **FR-007**: System MUST track workflow, timing, token, and outcome coverage independently for every supported report.
- **FR-008**: System MUST emit `INSUFFICIENT_EVIDENCE` when required coverage, sample size, correlation, or cohort matching is absent.
- **FR-009**: System MUST distinguish outcome quality, workflow economics, and operational health instead of collapsing them into one score.
- **FR-010**: System MUST include first-pass provisional completion, durable verification, reopen or equivalent recurrence, final-gate regression, and manual recovery in outcome evaluation.
- **FR-011**: System MUST include token cost, active wall time, invocation count, API round trips, tool calls, retries, and protocol rejection friction where their evidence is supported.
- **FR-012**: System MUST capture runtime-owned measured spans for supported operations and MUST NOT depend on agent-authored timing strings as the primary timing source.
- **FR-013**: System MUST calculate active wall time without double-counting overlapping intervals and MUST label summed resource time separately.
- **FR-014**: System MUST declare supported host, workflow, evidence, and complexity-cohort boundaries for every comparative report.
- **FR-015**: System MUST prevent unsupported cohorts from producing a positive improvement claim.
- **FR-016**: System MUST preserve privacy-safe boundaries by rejecting or sanitizing credentials, prompts, usernames, private machine identifiers, and unnecessary absolute local paths.
- **FR-017**: System MUST keep review resolution fail-open when optional host telemetry is absent while making malformed, unsafe, or unsupported evaluation input fail loudly.
- **FR-018**: System MUST attach stable runtime version, repository scope, PR scope, concern identity, producer attribution, and observation metadata to evaluation-ready archives.
- **FR-019**: System MUST define deterministic duplicate handling and MUST NOT count duplicate evidence as additional outcomes or samples.
- **FR-020**: System MUST expose the exact evidence deficits behind `INSUFFICIENT_EVIDENCE` so maintainers can distinguish unavailable data from product regressions.
- **FR-021**: System MUST distinguish expected control-flow rejections from actionable protocol or workflow failures before calculating rejection friction.
- **FR-022**: Comparative reports MUST expose runtime-version grouping, cohort dimensions, sample size, distribution summaries, and uncertainty sufficient to prevent unqualified global-average claims.
- **FR-023**: System MUST report evaluation-capture and report-generation overhead separately from measured workflow cost and MUST evaluate that overhead against a declared normal-path budget.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Evaluation consumes runtime and telemetry evidence but has no control-plane authority. Runtime projection, policy, command planning, execution evidence, and final-gate remain authoritative.
- **Runtime Kernel Model**: Runtime facts and execution results are inputs. The evaluation plane derives records and comparisons only after archival. No evaluation output is accepted as a runtime event source in this feature.
- **CLI / Agent Contract Impact**: Existing public runtime and agent contracts remain unchanged. Any evaluation command or machine-readable report is additive and versioned.
- **Evidence Requirements**: Provisional and durable verification are evaluation claims with explicit evidence boundaries; neither substitutes for runtime completion evidence.
- **Packaged Skill Boundary**: Repo-root runtime code owns capture, validation, projection, and reporting. `skill/` may document interpretation and routing but does not calculate evaluation truth.
- **External Intake Replaceability**: Evaluation records remain producer- and host-agnostic through versioned source attribution and supported capability declarations.
- **Telemetry Evidence Boundary**: Missing optional telemetry degrades comparison coverage without blocking review completion. Malformed or unsafe telemetry remains visible and fails evaluation ingestion.
- **Architecture Plateau Risk**: Evaluation must reuse one evidence projection and one comparison policy rather than duplicate workflow-specific scoring branches.
- **Fail-Fast Behavior**: Invalid evidence versions, ambiguous identity, unsafe content, unsupported comparisons, and contradictory verification inputs fail loudly.

### Key Entities *(include if feature involves data)*

- **Evaluation Record**: A read-only derived record for a concern, run, PR, or runtime version.
- **Verification Observation**: Evidence supporting provisional, durable, unknown, or negative outcome status.
- **Observation Boundary**: The declared later-review window and source capable of supporting durable verification.
- **Coverage Dimension Set**: Independent workflow, timing, token, and outcome evidence markers.
- **Supported Cohort**: Runs eligible for comparison because their host, workflow, evidence, and complexity dimensions satisfy declared rules.
- **Comparison Result**: Separate quality, economics, and operational-health conclusions or `INSUFFICIENT_EVIDENCE`.
- **Run Manifest**: Stable archive metadata used for correlation without becoming runtime truth.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every supported concern evaluation reports provisional and durable verification independently.
- **SC-002**: Concerns lacking a supported later observation are reported with unknown durable outcome and are never counted as durably verified.
- **SC-003**: A correlated reopen or equivalent recurrence prevents durable verification in 100% of replay contract cases.
- **SC-004**: Every supported comparison reports workflow, timing, token, and outcome coverage separately.
- **SC-005**: Missing required evidence, sample size, identity correlation, or cohort matching produces `INSUFFICIENT_EVIDENCE` instead of a positive improvement claim.
- **SC-006**: Lower cost cannot yield an improvement result when supported outcome guardrails regress.
- **SC-007**: Active wall time does not double-count overlapping intervals and never exceeds summed resource time for the same measured operations.
- **SC-008**: Missing optional host telemetry does not block review completion and produces an explicit degraded evaluation state.
- **SC-009**: Evaluation replay over the same archived evidence produces identical records and comparison results.
- **SC-010**: Evaluation attempts do not change runtime projection, policy, command plans, execution evidence, or final-gate outcomes.
- **SC-011**: Supported comparison reports expose sample size and at least median and upper-tail distribution summaries for cost and latency measures with enough samples to support them.
- **SC-012**: Evaluation overhead remains within the declared normal-path budget, and a budget breach is reported as operational-health degradation rather than review-resolution failure.

## Non-Goals

- Making evaluation output authoritative for runtime state or final-gate.
- Defining runtime-kernel migration slices or deleting legacy workflow paths; those belong to `024-runtime-consolidation`.
- Making command-session mode mandatory or changing output-truncation defaults.
- Supporting every historical archive, agent host, review producer, or PR complexity class in the first cohort.
- Producing one composite score that hides quality, cost, or operational-health tradeoffs.

## Assumptions

- Issue `#174` is the primary product requirement for this feature.
- Existing specs `011-agent-efficiency-metrics`, `015-external-agent-telemetry`, `019-cli-health-telemetry`, and `020-telemetry-decomposition` remain inputs rather than competing truth owners.
- The first useful delivery is additive: stable manifests, outcome observations, projections, and reports precede any runtime optimization decision.
- Durable verification requires a supported later observation; merge or elapsed time alone is insufficient unless explicitly introduced as a versioned observation contract later.
- Runtime-consolidation decisions in `024-runtime-consolidation` consume supported evaluation conclusions but evaluation never consumes rollout decisions as evidence.
