# Feature Specification: Layered OTel Workflow Modeling

**Feature Branch**: `027-otel-layered-model`  
**Created**: 2026-07-03  
**Status**: Draft  
**Input**: User description: "当前的otel设计是按照“产品时间线优先”,分层建模：层 1：保留当前 root CLI span；层 2：只把“真正独立可统计”的步骤升格为 child span；层 3：其余 checkpoint 继续保留 event，这个可以作为宪法保留下来，不过需要调研下，这种设计是否最合理。"

## Clarifications

### Session 2026-07-03

- Q: 如果 layered model 论证成功，它应获得什么级别的治理约束？ -> A: 升格为默认宪法原则，但允许带显式理由和验证证据的例外。
- Q: layered model 的“论证成功”需要什么级别的前置证据？ -> A: 只要 semantic / architecture 论证成立，就进入实现；查询与测试属于实现后的验证，不是采纳前置条件。
- Q: 哪些 representative workflow elements 必须纳入这次建模比较和分类？ -> A: 覆盖主流程，以及 subprocess、adapter call、retry/re-entry step 这些外部可见边界。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Decide Whether the Layered Model Becomes the Default (Priority: P1)

A maintainer responsible for the observability architecture needs a formal way
to decide whether the current layered OpenTelemetry model should become the
protected default for `gh-address-cr`, rather than treating the current design
as a permanent truth without comparative evidence.

**Why this priority**: This is the governing question behind the feature. If
the project cannot justify the model and its boundaries, every later telemetry
change remains arguable and expensive to review.

**Independent Test**: Present the specification and its supporting research to
an architecture reviewer and confirm they can determine, without reading code,
whether the project should keep, revise, or reject the layered model.

**Acceptance Scenarios**:

1. **Given** the project is evaluating its current telemetry model, **When**
   the reviewer reads the specification, **Then** the reviewer can identify the
   proposed layers, the reasons for each layer, and the questions that must be
   answered before constitutional adoption.
2. **Given** multiple plausible telemetry models exist, **When** the reviewer
   compares them using the specification, **Then** the reviewer can see which
   tradeoffs are considered acceptable for `gh-address-cr` and which are not.

---

### User Story 2 - Preserve Queryable Workflow Metrics Without Losing Product Timelines (Priority: P2)

An operator or product owner needs telemetry that still reads as a coherent
workflow timeline while also preserving trustworthy counts, latency, and error
signals for the workflow steps that matter independently.

**Why this priority**: The project adopted the current model to keep the CLI
timeline readable, but that readability only has value if it does not erase the
statistics and error boundaries needed for operational analysis.

**Independent Test**: For a representative review workflow, verify that the
specification makes it possible to answer three separate questions without
special-case reconstruction: "how many invocations happened", "which child
operations were slow", and "which checkpoints occurred during the run".

**Acceptance Scenarios**:

1. **Given** a workflow run containing a root invocation, independent child
   operations, and checkpoints, **When** the telemetry is interpreted through
   the specified model, **Then** invocation-level, child-operation-level, and
   checkpoint-level questions each have a distinct source of truth.
2. **Given** a step has an independently meaningful duration or error boundary,
   **When** the model classifies that step, **Then** it is not reduced to an
   event-only representation that hides its own count or latency distribution.

---

### User Story 3 - Give Contributors a Stable Promotion Rule for Spans vs Events (Priority: P3)

A contributor adding or modifying telemetry needs a stable rule for deciding
whether a workflow step remains a root-span attribute, becomes a child span, or
stays an event, so that future instrumentation changes do not drift based on
individual reviewer preference.

**Why this priority**: Without a stable decision rule, the project will
re-litigate the same telemetry boundary in every PR and gradually accumulate an
incoherent model.

**Independent Test**: Give a contributor a list of representative workflow
elements and confirm they can classify each one consistently using only the
specification's decision rules.

**Acceptance Scenarios**:

1. **Given** a workflow element with an independent duration, count, and error
   boundary, **When** a contributor applies the specification, **Then** the
   contributor classifies it as a child span candidate.
2. **Given** a workflow element that is only a timestamped checkpoint inside a
   larger operation, **When** a contributor applies the specification, **Then**
   the contributor classifies it as an event rather than a span.

### Edge Cases

- What happens when a workflow spans multiple short-lived CLI invocations and
  parent-child trace context is not available across process boundaries?
- How should the model classify steps that are frequent and low-value
  individually, but become meaningful when aggregated over many sessions?
- What happens when a step is locally cheap but externally visible, such as an
  adapter or subprocess boundary that users may need to count or time
  independently?
- How should the model handle a workflow that mixes deterministic runtime
  phases with optional or retried external calls?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The project MUST define a canonical three-layer telemetry model
  for workflow observability: root invocation span, independently measurable
  child operations, and checkpoint events.
- **FR-002**: The specification MUST describe the user value and analytical
  value of each layer in business terms, including what questions each layer is
  expected to answer.
- **FR-003**: The specification MUST define a promotion rule for when a
  workflow step qualifies as a child span, including independent duration,
  countability, error ownership, and product-analysis value.
- **FR-003a**: The first approved implementation slice MUST treat adapter
  execution and command-session operation execution as child span candidates
  because they already own independent duration, countability, and externally
  visible workflow value.
- **FR-004**: The specification MUST define when a workflow step remains an
  event, including checkpoints, state transitions, and point-in-time
  occurrences that do not need a separate duration boundary.
- **FR-004a**: The first approved implementation slice MUST keep high-level
  `preflight`, `session`, `ingest`, `gate`, and summary-style markers as events
  unless later evidence shows they deserve independent statistical treatment.
- **FR-005**: The specification MUST define the purpose and scope of the root
  invocation span for short-lived CLI commands and explain what it represents at
  the product timeline level.
- **FR-006**: The specification MUST define how multiple CLI invocations within
  one higher-level agent session are correlated when parent-child trace context
  is unavailable or incomplete.
- **FR-007**: The specification MUST identify the statistical distortions that
  occur when independently measurable operations are modeled only as events, and
  the readability/noise tradeoffs that occur when every internal step becomes a
  span.
- **FR-008**: The specification MUST compare the layered model against at least
  the following alternatives: single-root-span-plus-events only, fully nested
  span trees for all workflow steps, and session-wide trace reconstruction
  across multiple CLI invocations.
- **FR-008a**: The comparative evaluation scope MUST include the primary review
  workflow plus externally visible boundaries that are easy to misclassify,
  including subprocess steps, adapter calls, and retry or re-entry steps.
- **FR-009**: The specification MUST define what evidence is required before
  elevating the layered model into constitutional guidance, with semantic and
  architectural justification as the adoption gate and with query semantics or
  executable verification treated as post-adoption implementation validation
  rather than as pre-adoption prerequisites.
- **FR-009a**: If the layered model is adopted into constitutional guidance, it
  MUST be adopted as the default governance principle rather than an
  exception-free hard rule, and any deviation MUST carry explicit rationale,
  verification evidence, and reviewer-visible approval criteria.
- **FR-010**: The specification MUST preserve the project's telemetry evidence
  boundary by keeping telemetry as observed workflow evidence rather than review
  resolution state.
- **FR-011**: The specification MUST define how future telemetry additions are
  reviewed against the layered model so that contributors can tell whether a new
  workflow element belongs in the root span, a child span, or an event.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature affects telemetry governance and
  therefore touches a deterministic runtime concern. The runtime remains the
  owner of emitted telemetry and any future layer changes must be implemented in
  code rather than in docs-only guidance.
- **Runtime Kernel Model**: The feature governs how runtime workflow facts are
  represented observationally. External facts remain workflow operations,
  subprocesses, adapter calls, and checkpoints; the model determines which are
  represented as invocation spans, child spans, or events. Replay and contract
  tests remain required once implementation changes follow the specification.
- **CLI / Agent Contract Impact**: The feature does not immediately change the
  public command set, machine summaries, or exit semantics. If later adoption
  changes emitted telemetry fields or trace boundaries, those changes must
  preserve the current public Status-to-Action Map.
- **Evidence Requirements**: Constitutional adoption requires durable semantic
  and architectural evidence that the chosen model is coherent, comparable
  against alternatives, and reviewable without undocumented reasoning.
  Queryability and executable checks remain required after adoption during the
  implementation phase, but they are not the pre-adoption decision gate.
- **Governance Outcome**: A successful decision promotes the layered model to
  the default constitutional guidance for workflow telemetry, but exceptions
  remain allowed when they are explicit, justified, and backed by verification
  evidence.
- **Packaged Skill Boundary**: This feature is repo-root governance and
  specification work. No packaged `skill/` behavior is changed by the
  specification itself.
- **External Intake Replaceability**: The feature does not alter findings
  intake. It only constrains how workflow execution is observed after intake and
  orchestration occur.
- **Telemetry Evidence Boundary**: The feature must preserve source
  attribution, coverage honesty, public-safe metadata, and fail-open review
  resolution. It may refine span/event layering but must not let telemetry
  become authoritative runtime state.
- **Architecture Plateau Risk**: This feature exists to reduce future boundary
  ambiguity. If the research shows that the current layered model still creates
  unresolved ambiguity or repeated branching, the outcome must be "revise or
  reject", not "enshrine anyway".
- **Fail-Fast Behavior**: Any later implementation derived from this feature
  must fail loudly for malformed or unsafe telemetry data, while remaining
  fail-open for the core review-resolution workflow when optional enrichment is
  missing.

### Key Entities *(include if feature involves data)*

- **Root Invocation Span**: The top-level telemetry record representing one
  short-lived `gh-address-cr` CLI execution as a product-visible operation.
- **Child Operation**: A workflow step with its own meaningful duration, count,
  and error boundary that must remain independently queryable.
- **Checkpoint Event**: A point-in-time workflow occurrence used to explain the
  sequence of a larger operation without claiming a separate duration boundary.
- **Session Correlation Context**: The cross-invocation identifier used to group
  multiple CLI executions that belong to the same higher-level agent session or
  conversation.
- **Modeling Decision Record**: The rationale and evidence set used to justify
  whether the layered model is adopted, revised, or rejected as constitutional
  guidance.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Reviewers can classify 100% of the representative workflow
  elements in scope as root-span data, child spans, or events without using
  implementation-specific knowledge outside the specification.
- **SC-001a**: The representative workflow set used for classification includes
  at least one mainline workflow example, one subprocess boundary, one adapter
  call boundary, and one retry or re-entry boundary.
- **SC-002**: For every representative workflow in scope, the resulting model
  supports separate answers for invocation count, independently measurable step
  latency, and checkpoint sequencing without undocumented reconstruction.
- **SC-003**: The comparative research produces an explicit keep/revise/reject
  decision for the current layered model, with no unresolved ambiguity about why
  that decision was reached.
- **SC-004**: If the model is adopted as constitutional guidance, contributors
  can apply the promotion rule consistently enough that no representative
  workflow element remains uncategorized or multiply categorized.

## Assumptions

- The current single root CLI span remains the working baseline until the
  research and specification conclude that a different default is preferable.
- The project will evaluate the model using existing `gh-address-cr` workflow
  shapes rather than inventing abstract example flows unrelated to the product.
- The representative comparison set includes the main review workflow and
  externally visible boundaries such as subprocess, adapter, and retry or
  re-entry steps.
- Cross-process session grouping may continue to rely on correlation attributes
  when parent-child trace context cannot be propagated honestly across separate
  CLI invocations.
- The outcome of this feature may be to preserve, revise, or reject the current
  layered model; constitutional adoption is not assumed in advance.
- Even if adopted constitutionally, the model is assumed to govern by default
  with evidence-gated exceptions rather than as an unconditional universal
  rule.
- Adoption is assumed to be decided from semantic and architectural reasoning
  first; query validation and contract tests follow as implementation-proof
  work after that decision.
