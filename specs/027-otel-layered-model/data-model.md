# Data Model: Layered OTel Workflow Modeling

## Entity 1: Root Invocation Span

- **Purpose**: Represent one short-lived `gh-address-cr` CLI invocation as the
  product-visible top-level timeline unit.
- **Current owner**: `src/gh_address_cr/__main__.py` + `src/gh_address_cr/telemetry.py`
- **Key fields**:
  - `span.name`: `gh-address-cr.cli`
  - `service.version`
  - `gh_address_cr.command.name`
  - `process.*`
  - `gen_ai.*`
  - `vcs.*`
- **Validation rules**:
  - Exactly one root invocation span per process invocation
  - Root span remains fail-open and public-safe
  - Root span must not be replaced by a synthetic multi-invocation parent span

## Entity 2: Child Operation Span

- **Purpose**: Represent a workflow step with its own measurable duration,
  count, and/or error boundary.
- **Candidate sources**:
  - Adapter execution (`gh_address_cr.adapter`)
  - Command-session operation execution (`gh_address_cr.command_session.operation`)
  - Selected high-level workflow operations when they are analytically
    independent rather than narrative-only checkpoints
- **Key fields**:
  - `span.name`: operation-specific stable name
  - Operation identity attributes (command label, operation id/index, workflow phase)
  - Exit/outcome attributes when the child operation owns them
  - Optional product-analysis dimensions already present on the root or
    derivable from call-site state
- **Validation rules**:
  - Must be a true child of the current root invocation span
  - Must have explicit start and end timing in code
  - Must not duplicate checkpoint-only events as a second source of truth

## Entity 3: Checkpoint Event

- **Purpose**: Record meaningful point-in-time milestones inside a larger
  operation without creating an independent timing surface.
- **Current owner**: `add_current_span_event(...)` call sites in
  `high_level.py`, `command_runner.py`, and `command_session.py`
- **Key fields**:
  - `event.name`
  - Minimal contextual attributes required for sequencing or diagnostics
- **Validation rules**:
  - Event remains attached to the correct active span
  - Event should not own a separate duration contract
  - Event should avoid copying every parent span attribute
  - In the first implementation slice, high-level `preflight`, `session`,
    `ingest`, `gate`, and summary markers remain event-first

## Entity 4: Session Correlation Context

- **Purpose**: Group multiple CLI invocations belonging to one higher-level
  session without requiring true cross-process nesting.
- **Current owner**: `detect_agent_session(...)` and `sanitize_cli_argv(...)`
- **Key fields**:
  - `gen_ai.conversation.id`
  - `gen_ai.conversation.id.source`
  - `gen_ai.agent.name`
  - `vcs.change.id`
  - `vcs.repository.name`
- **Validation rules**:
  - Correlation attributes remain optional/fail-open
  - Correlation must not fabricate parent-child span relationships

## Classification State Machine

```text
Workflow element discovered
        |
        v
Does it own independent duration?
        |
   +----+----+
   |         |
  no        yes
   |         |
   v         v
Is it only a point-in-time       Does it also own count/error
checkpoint or annotation?        boundary or external analytical value?
   |                                  |
 +--+--+                           +--+--+
 |     |                           |     |
yes   no                          yes   no
 |     |                           |     |
 v     v                           v     v
event  revisit spec /         child span event unless a
       exception path                      new requirement appears
```

## Representative Workflow Set

The model must classify at least:

1. One mainline high-level review workflow
2. One adapter subprocess boundary
3. One command-session operation boundary
4. One retry or re-entry style boundary

## Relationships

- One **Root Invocation Span** contains zero or more **Child Operation Spans**
  and zero or more **Checkpoint Events**.
- One **Session Correlation Context** may relate multiple **Root Invocation
  Spans** across CLI invocations.
- A **Child Operation Span** may itself contain checkpoint events, but only if
  those events do not deserve separate child-span treatment.
