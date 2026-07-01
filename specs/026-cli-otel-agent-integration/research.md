# Phase 0 Research: Feasibility of CLI OTel Instrumentation for AI Agents

**Focus (per user directive)**: Can this land? — with special scrutiny on the
**AI-agent invocation / context-linking** dimension. Each item states a
**Decision**, **Rationale (with evidence)**, **Alternatives considered**, and a
**Landability verdict**. Verdicts feed the Human-Confirmation Gates in
[plan.md](./plan.md).

Evidence sources:
- OpenTelemetry CLI semantic conventions (status: **Development**) — `opentelemetry.io/docs/specs/semconv/cli/cli-spans/`
- OpenTelemetry Environment-Variable context carriers (status: **Beta**) — `opentelemetry.io/docs/specs/otel/context/env-carriers/`
- OpenTelemetry GenAI semantic conventions (status: **Development**, **moved** to `semantic-conventions-genai`) — `opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/`
- Local code inspection: `src/gh_address_cr/__main__.py`, `telemetry.py`, `core/telemetry_safety.py`, `cli.py`
- Installed SDK verification: `opentelemetry.semconv._incubating.attributes.{process,gen_ai}_attributes`, `TraceContextTextMapPropagator` — all import successfully in the pinned venv.

---

## R-001 — `process.command_args`: no existing full-argv sanitizer (Dimension 1)

**Decision**: Add a **new** public-safe full-argv sanitizer to
`core/telemetry_safety.py` (e.g. `safe_command_args(argv) -> list[str]`). Do NOT
reuse `command_label()`.

**Rationale**:
- `command_label(cmd)` (telemetry_safety.py:285) intentionally reduces an argv to
  a **single label token** (`executable [+ -m module] + first non-flag arg`). It
  drops flags, path-like tokens, and everything after the first positional. That
  is the opposite of Story 1's requirement, whose entire value is a **complete
  (sanitized) record of what the agent actually passed** ("判断 Agent 有没有乱传
  参数的铁证").
- The existing safety helpers (`_contains_token_marker`, `_contains_private_identifier`,
  `_looks_like_unnecessary_absolute_path`, `_safe_diagnostic_text`) are reusable
  **building blocks** for per-token redaction, but there is no function that maps a
  whole argv to a whole sanitized argv.
- The CLI + GenAI conventions both mark args as sensitive: CLI conventions say
  `process.command_args` "SHOULD NOT be collected by default unless there is
  sanitization that excludes sensitive data"; GenAI marks `gen_ai.tool.call.arguments`
  "may contain sensitive information". A new redactor is mandatory, not optional.

**Alternatives considered**:
- *Reuse `command_label`* → rejected: destroys the forensic value (single token only).
- *Store raw argv* → rejected: violates the telemetry public-safe boundary (Principle VIII).
- *Redact by argparse-aware parsing* → rejected for v1: couples the sanitizer to
  every subcommand's option schema; a token-level redactor (redact any token
  matching token/credential/private-id/abs-path markers, keep flags and safe
  positionals) is simpler and schema-agnostic.

**Landability verdict**: ✅ **LANDABLE**, but it is **new telemetry-safety
surface** and therefore requires executable contract tests (Principle V / AGENTS
"Testable Contracts"). Bounded and low-risk.

---

## R-002 — Context linking via `TRACEPARENT`: real spec, but not propagated by agents today (Dimension 2, THE CRUX)

**Decision**: Implement `TRACEPARENT` extraction as a **dormant, future-proofing**
path using `TraceContextTextMapPropagator().extract(...)` over an env carrier,
made the span's parent when present and well-formed. Document it explicitly as
*dormant* until agents adopt it. **Gate G-1.**

**Rationale (evidence)**:
- The OTel "Environment Variables as Context Propagation Carriers" spec is real
  and names "Command-line tools" as an explicit use case — but it is **Beta**,
  and it states plainly: *"The onus is on the application owner for receiving the
  set context from the SDK and passing it to its own process spawning mechanism.
  The language implementations MUST NOT handle spawning processes."* Translation:
  **propagation into a child process is never automatic** — the parent (the AI
  agent) must deliberately inject `TRACEPARENT` into the subprocess environment.
- **Empirical reality of the target callers**: mainstream coding agents do not do
  this today. Claude Code's OpenTelemetry support (`OTEL_*` config) exports *its
  own* metrics/logs; it is not known to inject a per-tool-call `TRACEPARENT` into
  the environment of Bash/tool subprocesses. Codex and generic agent runners are
  the same. So the "preferred / standard" path will be **exercised ~0% of the
  time in the field on day one**. This is the specific risk the user asked us to
  surface: *the standard mechanism is correct but adoption is absent.*
- Cost of building it anyway is near-zero and fail-open: if the env var is absent
  or malformed, we fall through to a root span (FR-005).

**Alternatives considered**:
- *Skip env extraction entirely* → rejected: it is cheap, standards-aligned, and
  becomes valuable the moment any agent adopts it; skipping would force a later
  re-open.
- *Invent a custom env var* → rejected: violates vendor-neutral, standards-first
  posture (Principle VIII "documented, vendor-neutral").

**Landability verdict**: ✅ **TECHNICALLY LANDABLE** as a dormant path, ⚠️ **but
delivers no present-day linkage**. Must not be marketed as working end-to-end
until a real agent injects the header. Needs **G-1** confirmation.

---

## R-003 — ppid fallback + attribute-name correction (Dimension 2, fallback)

**Decision**: When no `TRACEPARENT` is present, record the OS parent pid as the
**standard** attribute **`process.parent_pid`** (int), NOT the spec's proposed
`system.process.parent_id`. Treat it as a descriptive attribute only — it does
**not** alter trace/span identifiers. **Gate G-5** (spec update).

**Rationale**:
- `os.getppid()` is trivially available. But a ppid gives **no trace linkage** —
  it is an ephemeral, reused integer, not a trace/span id. Its value is weak
  ("which local process launched me"), useful only as a breadcrumb.
- The OTel process semantic conventions define **`process.parent_pid`** (Opt-In,
  int) as the standard key. `system.process.parent_id` (the spec's wording) is
  **not** a standard attribute name. Using the standard key keeps the data
  queryable alongside other process telemetry and avoids inventing a bespoke key
  (which Principle VIII discourages).

**Alternatives considered**:
- *Use `system.process.parent_id` as written* → rejected: non-standard name; no
  tooling recognizes it.
- *Synthesize a trace id from ppid* → rejected: fabricates correlation that does
  not exist; misleading.

**Landability verdict**: ✅ **LANDABLE** (rename to `process.parent_pid`). Low
value but honest and cheap. Requires a one-line **spec correction** (G-5).

---

## R-004 — GenAI attributes are unstable and have "moved" (Dimension 3, naming)

**Decision**: Use the installed `opentelemetry.semconv._incubating.attributes.gen_ai_attributes`
constants (`GEN_AI_OPERATION_NAME`, `GEN_AI_TOOL_NAME`, `GEN_AI_TOOL_CALL_ARGUMENTS`,
`GEN_AI_TOOL_CALL_RESULT`) and `process_attributes` constants, and pin/document
the SDK version. Accept possible upstream renames. **Gate G-4.**

**Rationale (evidence)**:
- Verified in the pinned venv: all four `gen_ai.*` constants and
  `process.parent_pid`/`process.command_args`/`process.exit.code` constants import
  and resolve to the expected string keys.
- **Instability signals**: the CLI convention is **Development**; the GenAI
  convention is **Development** AND the registry now marks these attributes
  **Deprecated → "Moved to the OpenTelemetry GenAI semantic conventions
  repository"** (`semantic-conventions-genai`). "Moved" ≠ removed, but names may
  churn. `execute_tool` is a documented well-known value for `gen_ai.operation.name`.
- Both `gen_ai.tool.call.arguments` and `gen_ai.tool.call.result` are typed `any`
  (object); on spans they MAY be recorded as a JSON string when structured form
  is unsupported — which is our case (span attributes are scalar/array), so we
  will record a **JSON string**.

**Alternatives considered**:
- *Hard-code string literals* → rejected: the `_incubating` constants are already
  present and self-documenting; literals drift silently.
- *Wait for stability* → rejected: would block the whole feature indefinitely; the
  values are usable now with a documented instability caveat.

**Landability verdict**: ✅ **LANDABLE** with a documented instability caveat
(G-4). Pin against `_incubating` constants.

---

## R-005 — `gen_ai.tool.call.result`: not capturable at the process span without CLI-internal plumbing (Dimension 3, result)

**Decision**: **Omit `gen_ai.tool.call.result` from v1.** Record
`gen_ai.operation.name`, `gen_ai.tool.name`, sanitized `gen_ai.tool.call.arguments`,
and the Dimension-1 exit outcome instead. **Gate G-3.**

**Rationale (evidence)**:
- `__main__.main()` calls `run_traced(tracer, "gh-address-cr.cli", lambda: cli_main(argv), ...)`.
  `cli_main(argv)` (cli.py:913) returns an **`int` exit code**. The
  machine-readable summary that agents actually consume is written to **stdout**
  by individual subcommands (high_level.py etc.), and is **never returned** to
  `__main__`. So at the process-span boundary there is *no result object to
  attach*.
- Capturing it would require either (a) intercepting/duplicating stdout in
  `__main__`, or (b) plumbing a structured result out of `cli_main` and every
  subcommand — both reach into CLI internals and enlarge the change well beyond
  "add attributes to the existing span" (violates AGENTS "smallest safe change").
- The forensic goal (Story 1) — *what did the agent send, and what happened* — is
  already met by sanitized `command_args` + `exit.code` + `error.type` without
  the result body.

**Alternatives considered**:
- *Tee stdout in `__main__`* → deferred: adds an I/O interception layer and a
  truncation/sanitization concern over arbitrary command output; needs its own
  safety review.
- *Return a result struct from `cli_main`* → deferred: broad refactor across all
  subcommands; a public-ish internal contract change.

**Landability verdict**: ⚠️ **NOT LANDABLE as-specified** without CLI-internal
plumbing. Omit in v1 (G-3); revisit as a scoped follow-up if the result body is
genuinely needed in the AI dashboard.

---

## R-006 — Exit-code / error-type recording on the existing span (Dimension 1)

**Decision**: Extend `run_traced` (or the `__main__` wrapper) to record
`process.exit.code` from `cli_main`'s return value and set a low-cardinality
`error.type` when the code is non-zero or an exception propagates. Keep the
existing sanitized-error behavior.

**Rationale**:
- Today `run_traced` sets start-time attributes and records a sanitized exception
  on failure, but does **not** capture the returned exit code as
  `process.exit.code`. The return value of the operation is available at the
  `with` block's exit, so recording it is a localized change.
- `error.type` must be low-cardinality (CLI convention): map to a small closed set
  (e.g. the sanitized exception class name, or `"nonzero_exit"` for a non-zero
  return without an exception, or the well-known `_OTHER`). Must be **unset on
  success** (exit 0).
- Must not inflate observed failure counts: a `SystemExit(0)`/return 0 is success;
  only genuine non-zero/exception paths set `error.type` (consistent with the
  existing `SystemExit` handling in run_traced).

**Alternatives considered**:
- *High-cardinality error strings (message text)* → rejected: violates the
  low-cardinality requirement and risks leaking sensitive text.

**Landability verdict**: ✅ **LANDABLE**. Localized change to `run_traced`/`__main__`.

---

## R-007 — Single-span constraint & export path unchanged (cross-cutting)

**Decision**: All new attributes attach to the **one** existing
`gh-address-cr.cli` span. No new span, tracer, processor, or exporter. The only
lifecycle change is that the span may now be created **with a remote parent
context** (R-002) when `TRACEPARENT` is present.

**Rationale**: FR-009 and Principle X (complexity budget) require attribute
extension, not a new subsystem. The export (BatchSpanProcessor → OTLP/HTTP to the
existing gateway, bounded timeouts) is untouched, so no performance or fail-open
regression.

**Landability verdict**: ✅ **LANDABLE**. This is the core reason the MVP stays
inside the protected baseline.

---

## R-009 — Passive agent-session correlation rescues Dimension 2 (Tier 2, demo-verified 2026-07-01)

**Decision**: Passively read a **registry** of host env vars and record
`gen_ai.conversation.id` (+ `.source`) and `gen_ai.agent.name`. Promote to v1 MVP.

**Rationale (live evidence)**: A demo inside a real Claude Code session found —
with **zero agent cooperation** — `CLAUDE_CODE_SESSION_ID` (a stable per-session
UUID, identical to the scratchpad path's session segment) and
`AI_AGENT=claude-code_..._agent` already present in the environment, while
`TRACEPARENT` was unset. Three simulated CLI invocations under an in-memory
exporter all carried the **same** `gen_ai.conversation.id`, proving
attribute-level session grouping works today. Both values passed the existing
`telemetry_safety` filters (non-token, non-private-id, non-abspath →
public-safe). Robustness: unlike `TRACEPARENT` (strict 55-char hex; a UUID is
invalid), an opaque conversation id needs no format and no agent-side OTel
tracer.

**Why this changes the earlier conclusion**: R-002's pessimism conflated
*correlation* with *span-tree nesting*. Nesting is still dormant (no
`TRACEPARENT`), but the User-Story-2 goal — "which agent session drove these
runs" — is achievable **today** via `gen_ai.conversation.id`. So Dimension 2 is
no longer "≈0% usable"; it is usable now for Claude Code.

**Alternatives considered**: generic `session.id` (rejected — GenAI
`conversation.id` is the domain-correct key, maps cleanly from OpenInference
`session.id`); only Claude Code (rejected — a small registry + generic override
`GH_ADDRESS_CR_CONVERSATION_ID` future-proofs other hosts at no cost).

**Landability verdict**: ✅ **LANDABLE & IN MVP.** No public flag, no skill
change (passive env). Fail-open (omit when absent).

---

## R-010 — VCS GitHub-PR mapping with privacy-preserving repo hash (Tier 1)

**Decision**: Map the CLI's own `owner/repo <pr>` arguments to `vcs.*`: plain
`vcs.change.id` (PR#) + `vcs.provider.name=github`; **hashed**
`vcs.repository.name` (one-way digest of `owner/repo`); conditional
`vcs.change.state` only from existing session data; **never** plain owner or
`vcs.repository.url.full`. Promote to v1 MVP.

**Rationale**: `vcs.*` is a real (Development) semconv family and gh-address-cr
is inherently PR-scoped, so the PR number = `vcs.change.id` maps perfectly and at
zero input cost (already parsed). This elevates the span from "which tool ran" to
"which PR was worked on", enabling per-PR / per-repo analytics. **Privacy is the
governing constraint** (Principle VIII): this is a *published* skill whose
telemetry flows to a shared gateway, so private-repo owner/repo names must not
leak. A stable one-way hash of `owner/repo` preserves *grouping* (same repo →
same hash) while removing the private identity — the confirmed Clarification.

**Alternatives considered**: full plain `vcs.*` (rejected — leaks private repo
identity for third-party installs); PR#+provider only (rejected — cannot
distinguish repos, low grouping value); plain repo name without owner (rejected —
repo name alone can still be private and loses org grouping).
`vcs.change.state` always-on (rejected — would force telemetry-driven GitHub
lookups; conditional-from-session keeps it fail-open and zero-latency).

**Landability verdict**: ✅ **LANDABLE & IN MVP** with an explicit privacy gate
(hash) and executable "no plain owner/URL" test.

---

## Consolidated feasibility summary

| Dimension | Piece | Verdict | Gate |
|---|---|---|---|
| 1 | `process.executable.name`, `process.pid` | ✅ Landable | — |
| 1 | `process.exit.code`, `error.type` | ✅ Landable (R-006) | — |
| 1 | `process.command_args` (new sanitizer) | ✅ Landable, new safety surface (R-001) | — |
| 2 | `TRACEPARENT` extraction | ✅ Landable but **dormant** (R-002) | **G-1** |
| 2 | ppid → `process.parent_pid` | ✅ Landable, low value, **rename** (R-003) | **G-5** |
| 2 | `--traceparent` public flag + skill instruction | ⚠️ Exceeds baseline — **defer** | **G-2** |
| 3 | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name` | ✅ Landable (R-004) | G-4 |
| 3 | `gen_ai.tool.call.arguments` (reuse sanitized argv) | ✅ Landable (R-001/R-004) | G-4 |
| 3 | `gen_ai.tool.call.result` | ⚠️ Not landable as-spec — **omit v1** (R-005) | **G-3** |
| 2 (Tier 2) | `gen_ai.conversation.id` + `gen_ai.agent.name` (passive env) | ✅ **Landable & IN MVP** — rescues Dim-2 today (R-009) | confirmed |
| Tier 1 | `vcs.change.id` + `vcs.provider.name` (plain), hashed `vcs.repository.name` | ✅ **Landable & IN MVP** — privacy hash (R-010) | confirmed |
| Tier 1 | `vcs.change.state` (conditional), plain owner/URL | ⚠️ state only-if-in-session; **owner/URL never plain** (R-010) | confirmed |

**Bottom line (updated 2026-07-01)**: Dimension 1 (forensics) and Dimension 3
(tool vocabulary) land cleanly. The Dimension-2 pessimism (R-002) is **partially
overturned by R-009**: full `TRACEPARENT` span-nesting is still dormant, but
passive `gen_ai.conversation.id` gives real session-level correlation **today**
for Claude Code — so Tier 2 is promoted into the MVP. Tier 1 VCS mapping is also
promoted with a privacy-preserving repo hash (R-010). The only paths still
deferred are those that would grow public CLI/skill surface (`--traceparent` G-2)
or need CLI-internal plumbing (`tool.call.result` G-3).
