# Research: Layered OTel Workflow Modeling

## Decision 1: Keep the root CLI span as the product-timeline anchor

- **Decision**: Preserve exactly one root `gh-address-cr.cli` span per CLI
  invocation as the default product-visible timeline anchor.
- **Rationale**: The repository already documents `otel-tracing.v1` as
  "one root span per CLI invocation" and existing tests/contracts assume that
  root shape. Replacing it with session-wide synthetic traces would expand
  runtime and contract surface without solving the immediate observability gap.
- **Alternatives considered**:
  - Session-wide synthetic trace reconstruction across separate invocations:
    rejected for the first slice because cross-process parentage is optional and
    correlation today is mostly attribute-based, not true parent-child context.
  - Root span plus events only forever: rejected because independently
    measurable operations already exist and event-only modeling hides their
    timing/count/error distributions.

## Decision 2: Use child spans only for independently measurable operations

- **Decision**: Promote a workflow step to a child span only when it owns an
  independent duration boundary, countability, error ownership, or externally
  visible analytical value.
- **Rationale**: OpenTelemetry trace guidance treats child spans as
  sub-operations with their own timing, while span events are better for
  meaningful singular points in time. This lines up with the repo's current
  distinction between operation timing and checkpoint narration.
- **Alternatives considered**:
  - Promote every existing phase marker to a child span: rejected because it
    increases span cardinality/noise without improving analytical truth.
  - Keep everything below the root as events: rejected because adapter calls and
    command-session operations already behave like standalone operations.

## Decision 3: Keep checkpoints as events unless they need independent statistics

- **Decision**: Keep phase markers such as `preflight`, `session`, `ingest`,
  `gate`, and summary transitions as span events unless a specific phase is
  shown to require separate latency/error/count analysis.
- **Rationale**: Current `high_level.py` instrumentation already models these as
  start/end events. They explain user-visible sequencing in Honeycomb without
  forcing every phase into a new child-span surface.
- **Alternatives considered**:
  - Convert all phase start/end pairs into child spans: rejected because many of
    them are internal checkpoints rather than independently actionable
    operations.

## Decision 4: First child-span candidates are adapter and command-session operation boundaries

- **Decision**: The first implementation slice should target:
  - `_run_adapter_command(...)`
  - per-operation execution inside `handle_command_session(...)`
  - only those high-level boundaries that prove to own independent timing or
    failure beyond checkpoint narration
- **Rationale**: These boundaries already capture duration and exit code, and
  are externally visible to operators or product analysis. They are the least
  ambiguous examples of "independently measurable" work in the current codebase.
- **Alternatives considered**:
  - Start with every phase in `HighLevelReviewRuntime.handle(...)`: rejected as
    too broad for a first slice.
  - Start with telemetry import/reporting paths: rejected because that is a
    different blast radius from the user-described workflow timeline concern.
- **Implementation status**: Implemented in the first slice with stable child
  span names `gh_address_cr.adapter` and
  `gh_address_cr.command_session.operation`.

## Decision 5: Session-level grouping remains correlation-first, not synthetic parentage

- **Decision**: Continue grouping multiple CLI invocations in one higher-level
  agent session via correlation attributes (`gen_ai.conversation.id`,
  `gen_ai.agent.name`, `vcs.*`) instead of inventing synthetic parent-child
  spans across process boundaries.
- **Rationale**: The repo already treats `TRACEPARENT` as optional/dormant and
  relies on passive session correlation today. The feature spec also fixed
  semantic/architectural reasoning as the adoption gate, not cross-process trace
  reconstruction.
- **Alternatives considered**:
  - Require true nested trace context across all invocations: rejected because
    it is not always honestly available and would shift the problem to host/tool
    orchestration rather than workflow modeling.

## Decision 6: The constitutional outcome is "default rule with explicit exceptions"

- **Decision**: If the layered model is adopted, it becomes the default
  constitutional guidance rather than an exception-free universal rule.
- **Rationale**: This matches the repo's complexity-budget principle. It avoids
  entrenching a rigid rule before every future telemetry boundary is known while
  still creating a default reviewer expectation.
- **Alternatives considered**:
  - Hard universal rule: rejected because future edge cases may need justified
    exceptions.
  - Spec-only local rule: rejected because the user explicitly wants the design
    to be governable and implementation-driving if the argument succeeds.

## Decision 7: Query semantics and tests validate implementation, not adoption

- **Decision**: Honeycomb queryability and executable tests are required after
  implementation, but not as the pre-adoption gate for this modeling decision.
- **Rationale**: The spec clarification fixed adoption on semantic and
  architectural reasoning first. That narrows planning: the plan must still
  produce concrete validation steps, but the argument does not wait on live
  telemetry proof to begin implementation.
- **Alternatives considered**:
  - Require Honeycomb evidence before code changes: rejected by clarified spec.

## Decision 8: High-level phase checkpoints stay event-first in the first slice

- **Decision**: `preflight`, `session`, `ingest`, `gate`, and summary-style
  high-level markers remain events on the root invocation span.
- **Rationale**: They improve timeline readability but do not yet justify their
  own independently queryable span surface.
- **Alternatives considered**:
  - Promote every high-level phase pair to child spans: rejected because that
    would increase span noise faster than it improves statistical truth.

## Source Notes

- OpenTelemetry trace concepts say child spans represent sub-operations, while
  span events represent meaningful singular points in time:
  https://opentelemetry.io/docs/concepts/signals/traces/
- OpenTelemetry trace API says child spans or events may represent
  sub-operations, with child spans measuring the timing of those operations:
  https://opentelemetry.io/docs/specs/otel/trace/api/
- OpenTelemetry event semantic guidance emphasizes that events represent
  structured point-in-time details and should not duplicate all span-level
  context:
  https://opentelemetry.io/docs/specs/semconv/general/events/
