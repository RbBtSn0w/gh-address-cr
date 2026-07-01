# Implementation Plan: CLI OpenTelemetry Instrumentation for AI Agent Scenarios

**Branch**: `026-cli-otel-agent-integration` | **Date**: 2026-07-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/026-cli-otel-agent-integration/spec.md`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Gate status**: G-1…G-5 confirmed 2026-07-01. **Tier 2** (passive
> agent-session correlation) and **Tier 1** (VCS GitHub-PR mapping) were
> confirmed and promoted into the v1 MVP via `/speckit-clarify` (see spec.md →
> Clarifications + Scope Decisions). This plan (re-run) propagates those two
> additions, which were empirically validated by a live demo on 2026-07-01.

## Summary

Add OpenTelemetry attributes to the **single existing** `gh-address-cr.cli` span
(`src/gh_address_cr/__main__.py`). The confirmed v1 MVP spans four attribute
families, all fail-open, all public-safe, no new span/tracer/pipeline, no public
CLI-flag change, no packaged-skill behavior change:

1. **Dimension 1 — Execution** (`process.*`): `executable.name`, `pid`,
   `exit.code` (synthetic `1` on exception), bounded `error.type`, and a **new**
   `safe_command_args` full-argv redactor (the repo has no full-argv sanitizer
   today — `command_label()` only reduces to a single label).
2. **Dimension 2 — Correlation, rescued by Tier 2** (`gen_ai.conversation.id`,
   `gen_ai.agent.name`, `process.parent_pid`, dormant `TRACEPARENT`): a live demo
   proved Claude Code already exports `CLAUDE_CODE_SESSION_ID` + `AI_AGENT` with
   zero cooperation, so a **passive host-env registry** groups a session's CLI
   invocations *today* without span nesting. `TRACEPARENT` extraction stays as a
   dormant future path.
3. **Dimension 3 — GenAI tool vocabulary** (`gen_ai.operation.name=execute_tool`,
   `gen_ai.tool.name`, `gen_ai.tool.call.arguments` reusing the sanitized argv).
   `gen_ai.tool.call.result` remains **deferred** (G-3).
4. **Tier 1 — VCS GitHub-PR mapping** (`vcs.*`): plain `vcs.change.id` (PR#) +
   `vcs.provider.name=github`; **hashed** `vcs.repository.name` (opaque digest of
   `owner/repo`); no plain owner/URL; conditional `vcs.change.state` only from
   existing session data.

## Technical Context

**Language/Version**: Python 3.10+ (`pyproject.toml`; local dev venv 3.14)
**Primary Dependencies**: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-api` (pinned, verified present), `requests`; stdlib `hashlib` (repo hashing), `os.environ` (passive session read) — no new third-party dependency
**Storage**: N/A — OTLP/HTTP export to the existing edge gateway; no new local state
**Testing**: `unittest` (`python3 -m unittest discover -s tests`); new files under `tests/`
**Target Platform**: Local-first CLI invoked by humans, CI, and AI agents (Claude Code confirmed to export session env; others via override env)
**Project Type**: Single-project CLI + packaged skill payload under `skill/`
**Performance Goals**: No hot-path latency; attribute assembly O(argv); one `hashlib` digest per PR-scoped invocation; telemetry stays fail-open with the existing bounded export (0.15s export / 0.2s shutdown)
**Constraints**: Single span (FR-009); no CLI exit-code/behavior change; every attribute passes the public-safe sanitation boundary; **no plain private owner/repo/URL leaves the process** (Clarifications)
**Scale/Scope**: One span per invocation; argv is small; env read is O(registry)

**Resolved unknowns** (all settled — no NEEDS CLARIFICATION remain):
- Do agents propagate `TRACEPARENT`? → No today (R-002); dormant.
- Can we correlate to the agent session *without* `TRACEPARENT`? → **Yes** — passive `CLAUDE_CODE_SESSION_ID` (R-009, demo-verified).
- Existing full-argv sanitizer? → No (R-001); new surface.
- `gen_ai.tool.call.result` at the span? → Not without CLI-internal plumbing (R-005); deferred.
- Semconv name stability? → Unstable/moved (R-004); pin via `_incubating` + value test.
- VCS privacy for a published skill? → Hash owner/repo; plain PR#+provider (R-010, Clarifications).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: ✅ PASS. Span lifecycle owned by
  `gh_address_cr.telemetry`; attribute content owned by
  `gh_address_cr.core.telemetry_safety`. No Markdown-owned state.
- **First-principles runtime kernel**: ✅ N/A (no new runtime state). Attribute
  extension to a pre-existing span. Architecture Preflight completed below.
- **Public CLI contract**: ✅ PASS. Tier 2 + VCS add **zero** public flags — Tier
  2 reads env passively; VCS derives from already-parsed `owner/repo <pr>`. The
  only deferred flag (`--traceparent`, G-2) stays out of scope. Status-to-Action
  Map unaffected.
- **Evidence-first handling**: ✅ N/A (observability evidence, not
  review-resolution evidence; MUST NOT substitute for reply/resolve/final-gate).
- **Packaged skill boundary**: ✅ PASS. All changes repo-root under `src/`. Tier 2
  needs **no** skill instruction (passive env), so unlike G-2 it does not touch
  the packaged payload.
- **External intake replaceability**: ✅ N/A.
- **Telemetry evidence boundary**: ✅ PASS, **strengthened**. Single span kept;
  source attribution kept; `process.command_args` and `gen_ai.tool.call.arguments`
  share one sanitized value. **Privacy is tightened**: `vcs.repository.name` is a
  one-way hash and plain owner/URL are never emitted — directly satisfying
  "reject/sanitize private identifiers". `gen_ai.conversation.id` /
  `gen_ai.agent.name` values pass the safety path (session UUID + product string
  are public-safe, demo-verified).
- **Architecture plateau discipline**: ✅ PASS. Adds attributes to one span; the
  only branch growth is a bounded host-env registry lookup and a
  PR-present/absent check, both finite and table-driven — not scattered
  conditionals. Two would-be public-surface branches (`--traceparent`, result
  plumbing) remain deferred.
- **Fail-fast verification**: ✅ PASS. New unittest coverage for the argv
  sanitizer, exit/error-type, ppid, GenAI attrs, **session detection**, and
  **VCS mapping incl. privacy (no plain owner/URL)**; smoke `--help`.

### Architecture Preflight (telemetry blast-radius trigger — attribute-surface + privacy growth)

| Preflight item | Resolution |
|---|---|
| Authoritative state owner | `gh_address_cr.telemetry` (span lifecycle) + `core.telemetry_safety` (attribute content: argv redaction, repo hashing, env registry). No new owner. |
| External facts / event inputs | `sys.argv`; process identity (`getpid`/`getppid`); exit code / exception; host env (`CLAUDE_CODE_SESSION_ID`, `AI_AGENT`, `GH_ADDRESS_CR_CONVERSATION_ID`, `TRACEPARENT`); parsed `owner/repo <pr>`; PR state if already in session data. |
| Projection / derived state | Flat attribute map on one span: sanitized argv; bounded error.type; **stable repo hash**; conversation/agent ids; `vcs.*`. No persisted projection. |
| Policy / decision function | (a) FR-004 parent-context resolver (env→root); (b) host-env→`gen_ai.*` **registry** (pure, table-driven); (c) argv→`vcs.*` mapper incl. PR-present check + hash. All deterministic, unit-testable in isolation. |
| Side-effect / outbox boundary | Existing BatchSpanProcessor → OTLP/HTTP. Unchanged. No new side-effect surface. |
| Artifact truth boundary + self-reference | None — spans are exported evidence, never read back as truth. No self-referential timing. |
| Privacy guard (new) | `vcs.repository.name` = one-way digest of `owner/repo`; plain owner + `vcs.repository.url.full` **never emitted**; all new string values routed through the public-safe sanitation path; tested by an explicit "no plain owner/URL/secret in any attribute" assertion. |
| Recovery / replay / contract tests | Fail-open on every context/env/VCS input (absent → omit attribute). New contract file asserts presence/absence, hash stability, and privacy. `--traceparent` fail-loud stays deferred. |
| Stop-and-escalate check | `--traceparent` flag, result-payload plumbing remain **deferred** (would grow public/skill surface). Tier 2 + VCS were *promoted* only because they add value with **no** public-contract/skill growth. |

**Preflight verdict**: Passes within the protected baseline; privacy decision is
explicit and testable.

## Project Structure

### Documentation (this feature)

```text
specs/026-cli-otel-agent-integration/
├── plan.md              # This file (updated re-run)
├── research.md          # Phase 0 — R-001..R-010 (adds R-009 session, R-010 VCS)
├── data-model.md        # Phase 1 — attribute/entity model incl. Tier 2 + VCS
├── quickstart.md        # Phase 1 — validation incl. session grouping + VCS privacy
├── contracts/
│   └── cli-otel-span-attributes.md   # C-1..C-12 (adds C-11 VCS, C-12 session)
└── checklists/requirements.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── __main__.py          # single span; set process.*, gen_ai.*, conversation/agent, vcs.*
├── telemetry.py         # run_traced (context + exit.code/error.type); resolve_parent_context
└── core/
    ├── telemetry_safety.py   # ADD: safe_command_args, derive_tool_name,
    │                         #   detect_agent_session (env registry), map_vcs_attributes (+repo hash)
    └── otel_semconv.py       # NEW: pinned _incubating constants (process.*, gen_ai.*, vcs.*, error.type)

tests/
├── test_otel_semconv_pins.py            # G-4 constant pins (incl. vcs.*, gen_ai.conversation.id)
├── test_telemetry_safety_command_args.py# safe_command_args redaction
├── test_telemetry_safety_vcs.py         # NEW: VCS mapping + hash stability + no plain owner/URL
├── test_cli_otel_execution.py           # US1 identity/exit/error + single-span/kind
├── test_cli_otel_context.py             # US2 TRACEPARENT/root/ppid + Tier2 session grouping
└── test_cli_otel_genai.py               # US3 gen_ai attrs, result absent
```

**Structure Decision**: Single-project CLI. All changes repo-root under `src/`
and `tests/`. **No `skill/` change** (Tier 2 is passive; no flag/instruction).

## Complexity Tracking

> Two Constitution items were CONDITIONAL only for the *deferred* remainder; the
> MVP (incl. Tier 2 + VCS) has no violations. Entries document deferred work.

| Deferred item (only if later accepted) | Why it might be needed | Simpler alternative used in v1 |
|---|---|---|
| `--traceparent` public flag + skill instruction (G-2) | Exact span-tree nesting when env propagation absent | Tier 2 `gen_ai.conversation.id` groups sessions today with no public/skill surface |
| `gen_ai.tool.call.result` plumbing (G-3) | Full tool-result visibility | `exit.code` + `error.type` + `vcs.*` + session grouping cover forensics/analytics |
| Plain `vcs.owner.name` / `vcs.repository.url.full` | Human-readable repo identity | Hashed `vcs.repository.name` groups per repo without leaking private names |

## Human-Confirmation Gates (all resolved)

G-1 dormant TRACEPARENT (build) · G-2 `--traceparent` flag (**defer**) · G-3
result (**defer**) · G-4 semconv pin (accept) · G-5 `process.parent_pid`
(applied). **Tier 2** (passive session) and **Tier 1** (VCS, hashed repo) —
**confirmed via /speckit-clarify 2026-07-01, in MVP.**
