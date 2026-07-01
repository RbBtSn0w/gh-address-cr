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
2. **Given** an unhandled exception propagates out of the CLI (a genuine
   crash), **When** the span is recorded, **Then** it carries a non-zero
   `process.exit.code` and a low-cardinality `error.type` describing the
   failure class.
2b. **Given** the CLI returns a non-zero *status* exit code that is a normal
   domain outcome (e.g. `WAITING_FOR_EXTERNAL_REVIEW` = exit 6, needs-action =
   exit 2), **When** the span is recorded, **Then** it records that
   `process.exit.code` honestly but sets **no** `error.type` (waiting/needs-action
   is not a failure — Principle VIII, no inflated error counts).
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
2a. *(v1-landable — Tier 2)* **Given** the host exports a session identifier
   (e.g. `CLAUDE_CODE_SESSION_ID`), **When** the CLI runs, **Then** the span
   records `gen_ai.conversation.id` (and `gen_ai.agent.name` from `AI_AGENT`),
   so multiple CLI invocations from the same agent session share one
   `gen_ai.conversation.id` and are groupable **today, without `TRACEPARENT`**.
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

### User Story 4 - Group CLI activity by the GitHub PR being worked on (Priority: P2)

Someone analyzing agent activity wants each `gh-address-cr` invocation tagged
with the GitHub PR it operated on, so they can retrieve "all CLI activity for
PR #123" or compare review-resolution effort across repositories — without a
CLI-specific query path and without the telemetry exposing private repository
names.

**Why this priority**: `gh-address-cr` is inherently PR-scoped, so the PR is the
natural grouping key for every other signal; it is P2 (alongside US2) because it
turns per-invocation spans into per-PR analytics. It is independent of US1/US2/US3.

**Independent Test**: run a PR-scoped command (`review acme/widgets 123`) and a
non-PR command (`version`); confirm the PR run carries the PR number, provider,
and a hashed repository id with no plain owner/URL, and the non-PR run carries no
`vcs.*` — and that the same repo hashes identically across runs.

**Acceptance Scenarios**:

1. **Given** a PR-scoped command `owner/repo <pr>`, **When** the span is
   recorded, **Then** it carries `vcs.change.id` (the PR number) and
   `vcs.provider.name = github` in plain text, and `vcs.repository.name` as a
   stable one-way hash of `owner/repo`.
2. **Given** any invocation, **When** the span is recorded, **Then** no attribute
   contains the plain `owner` name or `vcs.repository.url.full` (privacy).
3. **Given** a command that does not identify a PR (e.g. `version`, `doctor`),
   **When** the span is recorded, **Then** no `vcs.*` attribute is present.
4. **Given** the PR state is already available in session data, **When** the span
   is recorded, **Then** `vcs.change.state` is included; otherwise it is omitted
   (no telemetry-driven GitHub lookup).

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

## Clarifications

### Session 2026-07-01

- Q: VCS attribute privacy scope for a *published* skill whose telemetry flows to a shared gateway (private-repo owner/repo names are sensitive under Principle VIII) → A: Emit `vcs.change.id` (PR#) and `vcs.provider.name=github` in plain text; hash owner/repo into a **stable opaque id** stored in `vcs.repository.name`; do NOT emit plain owner or `vcs.repository.url.full`.
- Q: Emit `vcs.change.state` (open/merged/closed)? → A: Only when the PR state is **already present in session data** (zero extra cost, fail-open); omit otherwise — no telemetry-driven GitHub lookup.
- Q: Source design for `gen_ai.conversation.id` (passive env read) → A: An **extensible registry** — `CLAUDE_CODE_SESSION_ID` now, plus a generic override env `GH_ADDRESS_CR_CONVERSATION_ID` for other hosts; omit the attribute entirely when none is present (fail-open).

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
- **Tier 2 — passive agent-session correlation**: **PROMOTED INTO v1 MVP.**
  Empirically validated (2026-07-01): Claude Code already exports
  `CLAUDE_CODE_SESSION_ID` and `AI_AGENT` env vars with zero agent cooperation.
  The CLI passively reads them → `gen_ai.conversation.id` + `gen_ai.agent.name`,
  making all CLI invocations from one agent session **groupable today** without
  `TRACEPARENT`/span nesting. This rescues the "correlate a run back to the agent
  session" goal (US2) that the dormant G-1 path could not deliver on its own.
- **Tier 1 — VCS GitHub-PR mapping**: **PROMOTED INTO v1 MVP.** The CLI's own
  `owner/repo <pr>` arguments are mapped to `vcs.*` per the Clarifications above
  (plain `vcs.change.id` + `vcs.provider.name`; hashed `vcs.repository.name`;
  conditional `vcs.change.state`; no plain owner/URL). Elevates the span from
  "which tool ran" to "which GitHub PR was being worked on".

### Functional Requirements

- **FR-001**: The CLI's process-level span MUST record `process.executable.name`
  and `process.pid`, per the OpenTelemetry CLI semantic conventions, on every
  invocation.
- **FR-002**: The CLI's process-level span MUST record `process.command_args`
  only after the arguments pass through the existing public-safe sanitation
  path (rejecting or redacting tokens, credentials, usernames, and
  unnecessary absolute local paths); the raw, unsanitized argument list MUST
  NOT be attached to any exported span attribute.
- **FR-003**: The CLI's process-level span MUST record the honest
  `process.exit.code` on every invocation. `error.type` MUST be set **only when
  an unhandled exception propagates out of the CLI** (a genuine process
  failure/crash), using a low-cardinality bounded value. **A non-zero return
  value by itself MUST NOT set `error.type`**, because `gh-address-cr`
  deliberately overloads exit codes as a *status channel* (Status-to-Action Map,
  Principle II) — e.g. `WAITING_FOR_EXTERNAL_REVIEW` returns exit 6,
  `WAITING_FOR_FIX`/needs-action return exit 2, PR-IO preflight returns exit 5.
  Branding those normal waiting/needs-action outcomes as errors would inflate
  observed failure counts, violating Principle VIII. This is a documented
  deviation from the generic OTel CLI "error iff exit≠0" rule: here an *error* is
  a crash, and domain outcomes are carried by `process.exit.code` (and, when G-3
  lands, `reason_code`). `error.type` MUST NOT be set on any non-crash run
  (including a non-zero status exit). Span status is set ERROR only on a
  propagated exception, not on a domain non-zero return.
- **FR-004**: On startup, the CLI MUST establish caller trace context by this
  precedence (highest first), consistent with data-model Entity 3:
  **(1, highest) `--traceparent` flag** *[DEFERRED — G-2, NOT built in v1]* — an
  explicit flag that forces exact correlation, overriding the env; out of v1
  scope because it grows the public CLI contract and the packaged-skill layer.
  **(2) `TRACEPARENT` env** — a well-formed W3C value used as the span's remote
  parent context (built in v1 but **dormant**, G-1). **(3) `process.parent_pid`**
  — the OS parent pid recorded as a descriptive attribute only (never alters
  trace/span ids). In v1 only levels 2–3 exist; level 1 is deferred.
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
  context-linking inputs — in no case may a telemetry-layer failure change the
  CLI's own exit code or functional behavior. The only fail-loud path (a
  malformed explicit `--traceparent` flag value) belongs to the deferred G-2
  scope; **in v1 only the fail-open behavior is active and tested**, so this
  requirement is fully covered by the fail-open assertions (no v1 test gap).
- **FR-011** (Tier 2 — passive agent-session correlation): The CLI MUST
  passively read a known set of host environment variables and, when present,
  record `gen_ai.conversation.id` (from `CLAUDE_CODE_SESSION_ID`, else the
  generic override `GH_ADDRESS_CR_CONVERSATION_ID`) plus a `.source`
  sub-attribute naming the env var used, and `gen_ai.agent.name` (from
  `AI_AGENT`). The source set MUST be an extensible registry. When no known
  variable is present, the CLI MUST omit these attributes (fail-open) and MUST
  NOT require any agent cooperation, CLI flag, or skill change. The recorded
  values MUST pass the existing public-safe sanitation path.
- **FR-012** (Tier 1 — VCS GitHub-PR mapping): When the invoked command's
  arguments identify a GitHub PR (`owner/repo <pr_number>`), the CLI MUST record
  `vcs.change.id` (the PR number) and `vcs.provider.name = github` in plain
  text, and `vcs.repository.name` as a **stable, deterministic opaque hash** of
  `owner/repo` (same repo → same hash across runs). The CLI MUST NOT emit plain
  `owner` or `vcs.repository.url.full`. It MUST record `vcs.change.state`
  (open/closed/merged/wip) only when that state is already available in session
  data at zero extra cost, and MUST omit it otherwise (no telemetry-driven
  GitHub lookup). For commands that do not identify a PR (e.g. `version`,
  `doctor`), all `vcs.*` attributes MUST be omitted (fail-open).

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
  codes. The only potential surface addition is the deferred (G-2), optional,
  telemetry-only `--traceparent` flag (FR-004, highest precedence); it is **not
  built in v1** and would have no effect on command semantics, output, or the
  Status-to-Action Map.
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
- **Fail-Fast Behavior**: A malformed explicit `--traceparent` flag value
  (FR-004, highest precedence — **deferred G-2**) would fail loudly when built,
  since the caller explicitly requested exact correlation and a silently-ignored
  bad value would produce misleading trace data. In v1, all context-linking
  inputs (`TRACEPARENT` env, parent process id, session env, VCS args) fail open
  per FR-005/FR-010; there is no v1 fail-loud path.

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
- **Agent Session Context** (Tier 2): The passively-detected, public-safe
  session/agent identity (`gen_ai.conversation.id` from a host env registry,
  `gen_ai.agent.name` from `AI_AGENT`) that groups all CLI invocations of one
  agent session by attribute — independent of trace-context propagation.
- **VCS Change Context** (Tier 1): The GitHub-PR identity derived from the
  command arguments — `vcs.change.id` (PR number), `vcs.provider.name`, and a
  hashed `vcs.repository.name` — that ties the span to the PR being worked on
  without leaking the private owner/repo name or URL.

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
- **SC-007** (Tier 2, v1-testable): When the host exports a session identifier,
  multiple CLI invocations from the same agent session carry an identical
  `gen_ai.conversation.id`, so an operator can retrieve the full set of that
  session's CLI activity by a single attribute filter — no `TRACEPARENT` and no
  secondary log cross-referencing required.
- **SC-008** (Tier 1, v1-testable): CLI activity for a given GitHub PR is
  retrievable by filtering on `vcs.change.id` + hashed `vcs.repository.name`,
  and zero sampled spans expose the plain private owner name or repository URL.

## Assumptions

- "AI agent" callers in scope include, but are not limited to, Claude Code,
  Codex, and other automation that invokes `gh-address-cr` as a subprocess or
  tool call; this spec does not assume a single specific agent vendor.
- W3C Trace Context (the `traceparent` format) is the standard mechanism for
  *span-tree nesting* (Story 2), but it is dormant today (G-1). The **v1
  correlation primitive** is Tier 2 passive session detection
  (`gen_ai.conversation.id`), which groups a session's CLI invocations by
  attribute without requiring the agent to run its own OTel tracer.
- The stable hash used for `vcs.repository.name` (Tier 1) is a deterministic,
  non-reversible digest of `owner/repo`; the specific algorithm is an
  implementation detail fixed during planning, not a user-facing contract, and
  need not be cryptographically strong — only stable and collision-resistant
  enough to group per repository.
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
