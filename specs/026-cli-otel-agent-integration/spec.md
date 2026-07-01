# Feature Specification: CLI OpenTelemetry Instrumentation for AI Agent Scenarios

**Feature Branch**: `026-cli-otel-agent-integration`
**Created**: 2026-07-01
**Status**: Draft
**Input**: User description: "AI 场景下 CLI 工具 OTel 接入全景指南. 包含 semantice for cli 和 semantice for ai agent. 维度一：建立 CLI 基础执行视角 (Execution Span) ... 维度二：实现与 Agent 的上下文握手 (Context Linking) ... 维度三：注入 AI Agent 业务语义 (GenAI Context) ..."

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE - meaning if you implement just ONE of them,
  you should still have a viable MVP (Minimum Viable Product) that delivers value.
-->

### User Story 1 - Prove what the CLI actually received (Priority: P1)

An engineer investigating a suspicious or failed `gh-address-cr` run needs to know
exactly what command, arguments, and exit result the CLI process observed —
without asking the calling AI agent to reproduce the run or trusting the
agent's own self-reported log of what it "meant to do."

**Why this priority**: This is the baseline forensic capability the whole
feature exists for. Every other dimension (context linking, GenAI semantics)
is only useful once the execution facts themselves are trustworthy and
present on every invocation.

**Independent Test**: Run the CLI with a normal command and with a
deliberately malformed/unexpected argument set; confirm the exported span for
each run carries the process identity, the (sanitized) arguments actually
received, and a `process.exit.code`/`error.type` pair that matches the
observed outcome — with no reproduction step required.

**Acceptance Scenarios**:

1. **Given** the CLI is invoked with a valid command, **When** it exits
   successfully, **Then** the process span records `process.executable.name`,
   `process.pid`, `process.exit.code = 0`, and no `error.type`.
2. **Given** the CLI is invoked with arguments that cause it to fail,
   **When** it exits with a non-zero code or raises an unhandled error,
   **Then** the process span records that non-zero `process.exit.code` and a
   low-cardinality `error.type` describing the failure class.
3. **Given** the received arguments contain a credential, token, username, or
   unnecessary absolute local path, **When** the span is recorded, **Then**
   the sanitized value attached to `process.command_args` has that sensitive
   content removed or redacted, never the raw value.

---

### User Story 2 - Correlate a CLI run back to the agent turn that caused it (Priority: P2)

An operator watching AI-agent activity needs to connect a specific
`gh-address-cr` execution to the specific agent session/turn that invoked it,
so that a CLI-side problem (bad exit code, unexpected arguments) can be
traced back to *which* agent decision produced it, without stitching together
separate log systems by hand.

**Why this priority**: Execution facts alone (Story 1) tell you *what*
happened in the CLI process; this story tells you *who* asked for it. It
depends on Story 1's span existing but adds the cross-process link that
turns isolated CLI spans into part of a coherent agent trace.

**Independent Test**: Invoke the CLI once with a `TRACEPARENT` environment
variable set by a fake caller context, once with only a parent process id
available, and once with an explicit override flag; confirm each run links
to its caller through the correct, documented mechanism and that a run with
none of these present still completes normally as a root span.

**Acceptance Scenarios**:

1. **Given** the calling process sets a well-formed `TRACEPARENT` environment
   variable, **When** the CLI starts, **Then** its process span is created as
   a child of that remote trace context.
2. **Given** no `TRACEPARENT` is present but the OS parent process id is
   available, **When** the CLI starts, **Then** the span records the parent
   process id as an explicit attribute (not as trace-context linkage).
3. *(DEFERRED — G-2, not in v1)* **Given** a caller needs an exact, pre-agreed
   trace identifier regardless of environment propagation, **When** it supplies
   the documented `--traceparent` override flag, **Then** the CLI parses it and
   uses it for trace correlation instead of the environment-based mechanisms.
4. **Given** `TRACEPARENT` is present but malformed, **When** the CLI starts,
   **Then** the CLI still runs to completion as a root span; a broken context
   header MUST NOT block or fail the command.

---

### User Story 3 - See CLI tool calls in the same view as other AI tool activity (Priority: P3)

Someone building or reading AI-agent observability dashboards wants
`gh-address-cr` invocations to show up using the same tool-call vocabulary as
other AI tool calls (model calls, other CLI tools, MCP tools), so they can
filter, count, and reason about "what tools did this agent call" without a
CLI-specific carve-out.

**Why this priority**: This is the layer that makes the data *useful* to
AI-agent-focused tooling, but it only adds value once Stories 1 and 2 already
provide trustworthy, correlated execution facts to describe.

**Independent Test**: Invoke the CLI as part of a simulated agent tool call
and confirm the same process span additionally reports the tool-call
attributes, using the already-sanitized argument data (no second, unsanitized
copy) and a bounded-length result value.

**Acceptance Scenarios**:

1. **Given** the CLI runs to produce a result for its caller, **When** the
   process span is recorded, **Then** it also carries
   `gen_ai.operation.name = execute_tool` and a `gen_ai.tool.name` value.
2. **Given** the process span already has sanitized `process.command_args`,
   **When** `gen_ai.tool.call.arguments` is recorded, **Then** it reuses that
   same sanitized value and excludes CLI-internal/system-only flags (such as
   the `--traceparent` override flag from Story 2, deferred G-2).
3. *(DEFERRED — G-3, not in v1)* **Given** the CLI produces a long result
   payload, **When** `gen_ai.tool.call.result` is recorded, **Then** the value
   is truncated to a documented maximum length before being attached to the
   span. (v1 omits `tool.call.result`; see FR-008 and the Scope Decisions block.)

---

### Edge Cases

- What happens when the CLI is invoked directly by a human at a terminal
  (no `TRACEPARENT`, no meaningful parent-process trace context)? The span
  MUST still be recorded as a valid root span with all Story 1 attributes;
  Story 2/3 context-linking attributes are simply absent, not errored.
- How does the system handle a `TRACEPARENT` value that is syntactically
  present but invalid (wrong version, bad hex, wrong length)? The CLI MUST
  fail open — proceed as a root span — and MUST NOT crash or hang on a
  malformed header.
- *(DEFERRED — G-2)* What happens when both an environment `TRACEPARENT` and
  the explicit `--traceparent` flag are supplied at once? The explicit flag
  takes precedence, per the documented priority order (flag > environment >
  parent-process-id fallback). In v1 only the environment path exists.
- How does the system handle command-line arguments that are entirely
  sensitive (e.g., a bare token as a positional argument)? The sanitized
  value MUST redact or omit the sensitive content rather than passing through
  an empty-but-technically-safe placeholder that looks like real data.
- What happens when the CLI process itself fails before a span can be
  started (e.g., process/runtime crash prior to tracer initialization)? This
  is out of scope for span content and is bounded by the existing fail-open
  telemetry initialization behavior already in place.
- *(DEFERRED — G-3)* What happens when the CLI's final result is not text
  (e.g., structured JSON)? `gen_ai.tool.call.result` MUST be reduced to a
  bounded-length string representation before truncation is applied. Not
  applicable in v1 (result attribute omitted).

## Requirements *(mandatory)*

### Scope Decisions (v1 MVP — confirmed 2026-07-01)

The five feasibility gates from the plan are resolved as follows. v1 is the
protected-baseline MVP: no public CLI contract change, no packaged-skill
behavioral change.

- **G-1 — `TRACEPARENT` extraction**: **IN v1, but dormant.** Built (fail-open,
  near-zero cost) so the span nests under a caller trace when a caller injects a
  well-formed header; documented as dormant because no mainstream agent injects
  it today.
- **G-2 — `--traceparent` flag + skill instruction**: **DEFERRED** to a follow-up
  architecture spec. It is the only path to exact correlation when env
  propagation is absent, but grows the public CLI contract and the skill
  Behavioral Policy Layer and depends on the agent having its own OTel tracer.
- **G-3 — `gen_ai.tool.call.result`**: **DEFERRED** (see FR-008). If revived,
  record low-cardinality structured summary fields, never raw stdout.
- **G-4 — semconv instability**: **ACCEPTED.** Use
  `opentelemetry.semconv._incubating` constants plus a pin test asserting each
  key's string value; document the pinned SDK version.
- **G-5 — parent-pid attribute name**: **`process.parent_pid`** (standard,
  Opt-In int), not the non-standard `system.process.parent_id`.

### Functional Requirements

- **FR-001**: The CLI's process-level span MUST record `process.executable.name`
  and `process.pid`, per the OpenTelemetry CLI semantic conventions, on every
  invocation.
- **FR-002**: The CLI's process-level span MUST record `process.command_args`
  only after the arguments pass through the existing public-safe sanitation
  path (rejecting or redacting tokens, credentials, usernames, and
  unnecessary absolute local paths); the raw, unsanitized argument list MUST
  NOT be attached to any exported span attribute.
- **FR-003**: The CLI's process-level span MUST record `process.exit.code`
  on every invocation, and MUST record a low-cardinality, predictable
  `error.type` value whenever the exit code is non-zero or an unhandled
  exception propagates out of the CLI; `error.type` MUST NOT be set on a
  successful (exit code 0) run.
- **FR-004**: On startup, the CLI MUST attempt to establish caller trace
  context in this priority order: (1) a well-formed W3C `traceparent` value
  read from the `TRACEPARENT` environment variable, used as the span's
  remote parent context (built in v1 but **dormant** — see G-1); (2) if absent
  or malformed, the OS parent process id, recorded as the standard, descriptive
  `process.parent_pid` attribute only (not used to alter trace/span
  identifiers); (3) *[DEFERRED — G-2]* an explicit, documented `--traceparent`
  CLI flag that a caller may supply to force exact correlation, taking
  precedence over the above. Priority level (3) is **out of v1 scope** and
  deferred to a follow-up architecture spec because it grows both the public
  CLI contract and the packaged-skill behavioral layer.
- **FR-005**: A missing or malformed `TRACEPARENT` value, or an unset parent
  process id, MUST NOT cause the CLI to fail, hang, or change its exit
  behavior; the CLI MUST fall through to the next priority level and, at
  minimum, still emit the Story 1 execution span as a root span.
- **FR-006**: The CLI's process-level span MUST additionally record
  `gen_ai.operation.name = execute_tool` and a `gen_ai.tool.name` value
  identifying the invoked command, reflecting that `gh-address-cr` is
  fundamentally an AI-agent-facing tool-calling surface.
- **FR-007**: `gen_ai.tool.call.arguments` MUST be derived from the same
  sanitized value computed for `process.command_args` (FR-002) — no separate,
  differently-filtered copy — and MUST exclude any CLI-internal/system-only
  flags (such as the deferred `--traceparent` flag from FR-004).
- **FR-008** *[DEFERRED — G-3]*: `gen_ai.tool.call.result` is **out of v1
  scope**. `cli_main()` returns only an exit code; the machine-readable summary
  is written to stdout by subcommands and does not reach the process span, so
  capturing a result payload requires CLI-internal plumbing. If later accepted,
  it MUST record only low-cardinality structured summary fields (e.g. `status`,
  `reason_code`) rather than raw stdout, truncated to a documented bound. v1
  coverage of "what happened" is provided by `process.exit.code` + `error.type`.
- **FR-009**: All attributes introduced by this feature MUST be added to the
  existing single process-level span already established at CLI startup; this
  feature MUST NOT introduce an additional span, a second tracer, or a
  parallel telemetry export pipeline.
- **FR-010**: Sanitization and context-linking logic introduced by this
  feature MUST remain fail-open for missing, absent, or malformed
  context-linking inputs, and MUST fail loudly only for genuinely malformed
  telemetry-specific inputs (e.g., an explicit `--traceparent` flag value that is
  not a valid traceparent format) — in no case may a telemetry-layer failure
  change the CLI's own exit code or functional behavior.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature touches telemetry only. It adds
  attributes to the existing protected-baseline CLI process span; it does
  not change session state, GitHub IO, findings intake, loop safety, or
  final-gate behavior. The deterministic owner remains the existing
  `gh_address_cr.telemetry` module (span lifecycle) plus the existing
  telemetry-safety sanitation path (attribute content).
- **Runtime Kernel Model**: Not applicable — this feature does not add
  runtime state, projections, or policy decisions. It is a schema/attribute
  extension to the pre-existing single span already emitted around the CLI
  entrypoint.
- **CLI / Agent Contract Impact**: No change to `review`, other high-level
  commands, machine summary fields, reason codes, wait states, or exit
  codes. The only surface addition is one optional, telemetry-only flag
  (FR-004, priority level 3) for forcing an exact trace id; it has no effect
  on command semantics, output, or the Status-to-Action Map.
- **Evidence Requirements**: Not applicable to review-item evidence — this
  feature produces observability evidence about CLI execution and agent tool
  calls, not review-resolution evidence, and MUST NOT be treated as a
  substitute for reply/resolve/final-gate evidence.
- **Packaged Skill Boundary**: No packaged-skill changes are required;
  instrumentation lives entirely in the repo-root CLI entrypoint and
  telemetry module, consistent with the existing Thin Adapter boundary.
- **External Intake Replaceability**: Not applicable — this feature does not
  touch findings intake or review-producer coupling.
- **Telemetry Evidence Boundary**: This feature extends, and must remain
  consistent with, the existing telemetry evidence boundary: it stays
  observed workflow evidence, not review-resolution state. Source
  attribution is unchanged (single process span per invocation). Public-safe
  handling is extended, not relaxed: `process.command_args` and
  `gen_ai.tool.call.arguments` MUST both pass through the existing
  sanitization path before export, and `error.type`/exit-code recording MUST
  NOT inflate or alter observed failure counts.
- **Architecture Plateau Risk**: This feature is presumed low-risk under
  Principle X because it adds attributes to an already-existing single span
  rather than a new subsystem, spans, tracer, or state engine — it reduces
  investigative ambiguity (Story 1) without adding branches, flags, or
  fallbacks beyond the documented three-level context-linking priority
  order in FR-004, which is itself bounded and finite.
- **Fail-Fast Behavior**: A malformed explicit `--traceparent` override flag value
  (FR-004, priority level 3) MUST fail loudly, since the caller explicitly
  requested exact correlation and a silently-ignored bad value would produce
  misleading trace data. All other context-linking inputs (`TRACEPARENT`,
  parent process id) MUST fail open per FR-005.

### Key Entities

- **CLI Process Span**: The single, existing process-level OpenTelemetry
  span emitted once per CLI invocation. This feature adds attributes to it;
  it does not add a new entity.
- **Sanitized Argument Set**: The filtered representation of the CLI's
  received command-line arguments, already produced by the existing
  telemetry-safety path, and now shared as the single source for both
  `process.command_args` and `gen_ai.tool.call.arguments`.
- **Caller Trace Context**: The externally-supplied correlation identifier
  (from `TRACEPARENT`, OS parent process id, or the explicit override flag)
  used to link the CLI process span to the calling agent's own trace.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Given only the exported telemetry for a flagged CLI run,
  an engineer can determine the exact arguments the CLI received and the
  resulting exit outcome without reproducing the run, for 100% of
  investigated cases.
- **SC-002** *(dormant precondition — NOT a v1 acceptance gate)*: **When** the
  calling agent propagates a well-formed `TRACEPARENT` (G-1 dormant path), the
  CLI span correctly nests under the caller's trace, so an operator can trace
  the run back to the originating agent turn using telemetry alone. Because no
  mainstream agent injects `TRACEPARENT` today, the field link rate is ≈0% in
  v1; the v1-testable form of this criterion is the deterministic assertion
  "given an injected well-formed header, the span parent equals it" (US2 T010),
  not a population-percentage target.
- **SC-003**: CLI tool-call activity appears alongside other AI tool-call
  activity in a shared observability view using common tool-call attributes,
  without requiring a CLI-specific ingestion path.
- **SC-004**: Zero sampled exported spans contain a raw credential, token,
  username, or unnecessary absolute local path in any attribute, verified
  across a representative sample of runs including at least one run with
  deliberately sensitive input.
- **SC-005**: The default interactive/human CLI workflow requires zero new
  mandatory flags or environment variables; all context-linking mechanisms
  remain optional and additive.
- **SC-006**: A CLI run with a malformed or absent trace-context input
  (missing/garbled `TRACEPARENT`, unavailable parent process id) still
  completes with its original exit code in 100% of cases — telemetry never
  changes functional CLI behavior.

## Assumptions

- "AI agent" callers in scope include, but are not limited to, Claude Code,
  Codex, and other automation that invokes `gh-address-cr` as a subprocess or
  tool call; this spec does not assume a single specific agent vendor.
- W3C Trace Context (the `traceparent` format) is adopted as the standard
  propagation mechanism for Story 2; no other propagation format is in
  scope.
- Because `gh-address-cr` is inherently an AI-agent-facing control plane
  (per existing project scope), GenAI tool-call attributes (Story 3) are
  populated on every invocation rather than conditionally gated on detecting
  an "agent vs. human" caller — there is no reliable way to distinguish
  those cases, and the attributes are harmless additive metadata either way.
- `gen_ai.tool.name` is populated using the invoked top-level command name
  (e.g., `review`, `final-gate`) when identifiable, falling back to the CLI
  entrypoint name otherwise — this matches the existing public command
  surface (Principle II) rather than inventing a separate tool-naming
  scheme.
- The maximum length used to truncate `gen_ai.tool.call.result` is an
  implementation detail to be fixed during planning, not a user-facing
  contract.
- This feature extends the single existing process span (`gh-address-cr.cli`
  in `src/gh_address_cr/__main__.py`); it does not introduce per-subcommand
  child spans.
- The upstream OpenTelemetry CLI and GenAI semantic conventions are
  currently published under "Development" status; this spec targets the
  attribute names as currently published and accepts that upstream renames
  may require a follow-up update.
