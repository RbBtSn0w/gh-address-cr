# Implementation Plan: CLI OpenTelemetry Instrumentation for AI Agent Scenarios

**Branch**: `026-cli-otel-agent-integration` | **Date**: 2026-07-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/026-cli-otel-agent-integration/spec.md`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Gate status**: All five gates (G-1…G-5) were **confirmed on 2026-07-01** and
> are now fixed decisions in [spec.md](./spec.md) → *Scope Decisions (v1 MVP)*.
> The "Human-Confirmation Gates" / "Recommendation" language below is retained as
> the decision rationale record — it is no longer pending.

> **Planning directive from the user**: This plan is primarily a **feasibility
> investigation** ("上述细节主要调研是否可以落地"), with special scrutiny on the
> **AI-agent invocation / context-linking** dimension. Anything that exceeds the
> landable protected baseline is flagged **HUMAN CONFIRMATION REQUIRED** rather
> than silently scoped in. See [research.md](./research.md) for the evidence
> behind every verdict below.

## Summary

The feature adds OpenTelemetry CLI + GenAI semantic-convention attributes to the
**single existing process span** (`gh-address-cr.cli` in
`src/gh_address_cr/__main__.py`). Research splits the three requested dimensions
into a **landable MVP** and a **confirmation-gated remainder**:

- **Dimension 1 (Execution Span) — LANDABLE.** `process.executable.name`,
  `process.pid`, `process.exit.code`, and `error.type` are all directly
  obtainable. The one non-trivial piece is `process.command_args`: the repo has
  **no** full-argv sanitizer today (`command_label()` reduces argv to a single
  label, it does not redact a full arg vector), so a new public-safe argv
  redactor is required. This is new telemetry-safety surface.
- **Dimension 2 (Context Linking) — PARTIALLY LANDABLE, CRUX RISK.** The
  `TRACEPARENT` env-carrier mechanism is a real (Beta) OTel spec, but propagation
  to a child process is **never automatic** — the calling agent must voluntarily
  inject it, and **no mainstream coding agent (Claude Code, Codex) is known to do
  so today**. So the "preferred" path is a *dormant, future-proofing* path, not
  present-day linkage. The ppid fallback is landable but low-value; the original
  spec draft used a **non-standard attribute name** (`system.process.parent_id`),
  now **resolved in spec.md to the standard `process.parent_pid`** (G-5). The
  `--traceparent` flag adds a
  **public CLI contract surface** and only works if the **skill payload instructs
  the agent to generate and pass it** — both exceed the baseline.
- **Dimension 3 (GenAI Context) — SPLIT.** `gen_ai.operation.name=execute_tool`
  and `gen_ai.tool.name` are landable. `gen_ai.tool.call.arguments` reuses the
  Dimension-1 sanitized argv (landable). `gen_ai.tool.call.result` is **NOT
  landable as-specified**: `cli_main()` returns only an `int` exit code — the
  machine-readable summary is written to stdout by subcommands and never reaches
  the process span, so capturing a result payload requires reaching into CLI
  internals (stdout capture or result plumbing).

**Recommended landable MVP** (protected-baseline, no public CLI contract change,
no skill behavioral change): Dimension 1 (incl. new argv sanitizer) +
`process.parent_pid` attribute + Dimension 3 minus `tool.call.result`. Everything
else is deferred behind explicit human confirmation.

## Technical Context

**Language/Version**: Python 3.10+ (enforced by `pyproject.toml`; local dev venv is 3.14)
**Primary Dependencies**: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-api` (already vendored/pinned; verified present), `requests`
**Storage**: N/A — telemetry is exported over OTLP/HTTP to the existing edge gateway; no new local state
**Testing**: `unittest` (`python3 -m unittest discover -s tests`); existing suite `tests/test_otel_telemetry.py`
**Target Platform**: Local-first CLI (`gh-address-cr`) invoked by humans, CI, and AI coding agents (Claude Code, Codex, others)
**Project Type**: Single-project CLI + packaged skill payload under `skill/`
**Performance Goals**: No added latency on the hot path — telemetry stays fail-open with the existing bounded export (0.15s export timeout, 0.2s shutdown join); attribute assembly must be O(argv length)
**Constraints**: Must not change CLI exit codes or functional behavior; all span attributes must pass the existing public-safe sanitation boundary; must remain the **single** process span (no new span/tracer/pipeline)
**Scale/Scope**: One span per CLI invocation; argv length is small (tens of tokens); result truncation bound is an internal constant

**Resolved unknowns** (were NEEDS CLARIFICATION, now settled in research.md):
- Do agents propagate `TRACEPARENT`? → **No, not today** (R-002). Preferred path is dormant.
- Is there an existing argv sanitizer to reuse? → **No** (R-001). New surface required.
- Can `gen_ai.tool.call.result` be captured at the process span? → **Not without CLI-internal plumbing** (R-005).
- Are the semconv attribute names stable? → **No** — CLI convention is "Development", GenAI convention is "Development" and has **moved** to a separate repo (R-004).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: ✅ PASS. Telemetry span lifecycle stays owned by
  the deterministic `gh_address_cr.telemetry` module; attribute content stays
  owned by the `telemetry_safety` sanitation path. No Markdown-owned state.
- **First-principles runtime kernel**: ✅ N/A (no new runtime state). This is an
  attribute extension to a pre-existing span, not a new state machine. The
  Architecture Preflight (below) is still completed because the change touches
  the telemetry contract and (in the gated remainder) the CLI contract.
- **Public CLI contract**: ⚠️ CONDITIONAL. The MVP preserves the contract fully.
  The **gated `--traceparent` flag** would add a global public flag → requires
  explicit versioning + human confirmation. Status-to-Action Map is unaffected
  either way (telemetry-only flag, no effect on command semantics/output).
- **Evidence-first handling**: ✅ N/A. This produces observability evidence, not
  review-resolution evidence; it MUST NOT be treated as reply/resolve/final-gate
  evidence (spec Constitution Alignment).
- **Packaged skill boundary**: ⚠️ CONDITIONAL. The MVP is repo-root only
  (`src/`), no `skill/` change. The **gated `--traceparent` path requires the skill
  to instruct the agent** to generate/pass a trace id — that is a
  Behavioral-Policy-Layer change to the payload → human confirmation.
- **External intake replaceability**: ✅ N/A. No findings-intake coupling.
- **Telemetry evidence boundary**: ✅ PASS (extended, not relaxed). Single span
  preserved; source attribution unchanged; `process.command_args` and
  `gen_ai.tool.call.arguments` share one sanitized value through the existing
  safety path; `error.type`/exit-code recording must not inflate observed
  failure counts; core flows stay fail-open.
- **Architecture plateau discipline**: ✅ PASS. Adds attributes to one existing
  span rather than new branches/flags/state. The only added branch is the
  bounded 3-level context-linking priority order (FR-004) — and the plan
  **defers** the two branches that would grow public surface rather than
  patching them in silently.
- **Fail-fast verification**: ✅ PASS. New unittest coverage for the argv
  sanitizer, exit-code/error-type recording, ppid attribute, and the
  GenAI attributes; smoke check `python3 -m gh_address_cr --help`.

### Architecture Preflight (required — blast-radius trigger: telemetry contract + potential CLI contract)

| Preflight item | Resolution |
|---|---|
| Authoritative state owner | `gh_address_cr.telemetry` (span lifecycle) + `gh_address_cr.core.telemetry_safety` (attribute content). No new owner. |
| External facts / event inputs | `sys.argv` (received args), process identity (`os.getpid`/`os.getppid`), CLI exit code / raised exception, `TRACEPARENT` env (gated), `--traceparent` flag value (gated). |
| Projection / derived-state shape | A flat attribute map on the single process span. No persisted projection. |
| Policy / decision function | The FR-004 context-linking priority resolver (flag > env > ppid-attribute > root). Pure function over the three inputs; deterministic; unit-testable. |
| Side-effect / outbox boundary | The existing BatchSpanProcessor → OTLP/HTTP export. Unchanged. No new side-effect surface. |
| Artifact truth boundary + self-reference risk | None — spans are exported evidence, never read back as authoritative state. No self-referential timing. |
| Recovery / replay / contract tests | Fail-open on all context-linking inputs (malformed `TRACEPARENT`, absent ppid). New unittest contract file asserts attribute presence/absence and sanitization; malformed-`--traceparent` fails loud (gated). |
| **Stop-and-escalate check** | The `--traceparent` public flag + skill behavioral change + result-payload plumbing each *grow* public surface/state. Per AGENTS.md ("if feedback repeatedly adds edge branches in the same axis... create/update an architecture spec instead"), these are **deferred to human confirmation**, not patched in. |

**Preflight verdict**: The MVP subset passes within the protected baseline. The
gated remainder is correctly held for human confirmation.

## Project Structure

### Documentation (this feature)

```text
specs/026-cli-otel-agent-integration/
├── plan.md              # This file
├── research.md          # Phase 0 — feasibility verdicts + evidence (centerpiece)
├── data-model.md        # Phase 1 — attribute/entity model + context-linking resolver
├── quickstart.md        # Phase 1 — how to validate the instrumentation locally
├── contracts/
│   └── cli-otel-span-attributes.md   # Phase 1 — the span attribute contract
└── checklists/
    └── requirements.md  # Spec quality checklist (from /speckit-specify)
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── __main__.py          # Owns the single process span; call site to extend with
│                        #   parent-context resolution + exit-code/args/genai attrs
├── telemetry.py         # Span lifecycle; extend run_traced to record exit code
│                        #   and to accept a resolved parent context
└── core/
    └── telemetry_safety.py   # ADD: public-safe full-argv sanitizer (new surface)

tests/
├── test_otel_telemetry.py         # existing suite (unchanged)
├── test_otel_semconv_pins.py      # NEW: G-4 constant string-value pins
├── test_telemetry_safety_command_args.py  # NEW: safe_command_args redaction
├── test_cli_otel_execution.py     # NEW: identity + exit-code/error-type (US1)
├── test_cli_otel_context.py       # NEW: TRACEPARENT parent / root fallback / ppid (US2)
└── test_cli_otel_genai.py         # NEW: gen_ai attrs, result absent (US3)
```

**Structure Decision**: Single-project CLI. All MVP changes are repo-root under
`src/gh_address_cr/` and `tests/`. **No `skill/` payload change in the MVP** — the
packaged-skill boundary is only touched by the *gated* `--traceparent` behavioral
instruction, which is deferred.

## Complexity Tracking

> Filled because two Constitution items are CONDITIONAL (public CLI contract,
> packaged skill boundary). The MVP avoids all violations; the entries below
> document the **deferred** work so the boundary decision is explicit.

| Violation (only if the gated item is later accepted) | Why it might be needed | Simpler alternative preferred in the MVP |
|---|---|---|
| New global `--traceparent` public CLI flag | Only mechanism giving *exact* caller-chosen trace correlation when env propagation is absent | MVP uses `process.parent_pid` attribute + dormant `TRACEPARENT` extraction; no new public flag until an agent actually needs exact correlation |
| Skill-payload instruction telling the agent to generate/pass a trace id | The `--traceparent` flag is useless unless the agent is told to populate it | MVP adds zero skill behavioral change; context linking is opportunistic, not agent-mandated |
| `cli_main` result-payload plumbing / stdout capture for `gen_ai.tool.call.result` | Full tool-call result visibility in the AI dashboard | MVP omits `tool.call.result` (records `operation.name`, `tool.name`, sanitized `tool.call.arguments`, and exit outcome instead) |

## Human-Confirmation Gates (explicit, per user directive)

The following exceed the landable baseline and MUST be confirmed before build:

1. **G-1 — `TRACEPARENT` dormant path**: Build now (future-proof, no cost when
   absent) vs. defer until an agent demonstrably injects it? *Recommendation:
   build the extraction (it is fail-open and cheap), but label it dormant in
   docs so no one over-claims present-day linkage.*
2. **G-2 — `--traceparent` public CLI flag + skill instruction**: In scope? This is
   the only path to exact correlation but grows public CLI + skill surface.
   *Recommendation: defer to a follow-up architecture spec.*
3. **G-3 — `gen_ai.tool.call.result` capture**: Accept CLI-internal plumbing to
   surface the result payload, or omit it in v1? *Recommendation: omit in v1;
   revisit once result plumbing is justified.*
4. **G-4 — Attribute-name instability**: The CLI + GenAI conventions are
   "Development"/"Moved". Accept possible future renames (pin against the
   installed `opentelemetry.semconv._incubating` constants and document the
   version)? *Recommendation: accept, using `_incubating` constants + a pinned
   note.*
5. **G-5 — `system.process.parent_id` vs `process.parent_pid`**: The original
   draft name was non-standard. **CONFIRMED & applied**: spec.md now uses the
   standard `process.parent_pid` (Opt-In in the process semconv).
