# Phase 1 Data Model: CLI OTel Span Attributes

This feature adds **no persisted entities**. The "model" is the attribute set on
the single existing process span plus one pure decision function. All names use
the installed `opentelemetry.semconv._incubating` constants (see research.md R-004).

## Entity 1 — CLI Process Span (existing, extended)

The single span `gh-address-cr.cli` created in `src/gh_address_cr/__main__.py`.
Span kind: `INTERNAL` (CLI callee, per CLI convention). Attributes:

| Attribute | Type | Requirement | Source | Notes |
|---|---|---|---|---|
| `process.executable.name` | string | Required | `os.path.basename(sys.argv[0])` or `"gh-address-cr"` | Base name only. |
| `process.pid` | int | Required | `os.getpid()` | |
| `process.exit.code` | int | Required | honest `cli_main` return (incl. non-zero **status** codes 2/5/6); synthetic `1` on propagated exception | Always present, incl. exception path (R-006, U1). |
| `error.type` | string | Conditional (**exception only**) | enumerated literals: `"keyboard_interrupt"` (KeyboardInterrupt), `"timeout"` (TimeoutError), else `"_OTHER"` | Set **only on a propagated exception (crash)**, never on a non-zero status return (Principle VIII, F1); no raw class names (A2). |
| `process.command_args` | string[] | Recommended | `safe_command_args([sys.argv[0]] + (argv if argv is not None else sys.argv[1:]))` | Sanitized (R-001). Never raw. Argv source pinned for test determinism (see Entity 2). |
| `process.parent_pid` | int | Opt-In | `os.getppid()` | Fallback breadcrumb only (R-003); **replaces** spec's `system.process.parent_id` (G-5). |
| `gen_ai.operation.name` | string | Added | constant `"execute_tool"` | |
| `gen_ai.tool.name` | string | Added | parsed top-level command (e.g. `review`), else `"gh-address-cr"` | Matches public command surface. |
| `gen_ai.tool.call.arguments` | string (JSON) | Added | JSON of the **same** `safe_command_args` value (no system-only flags exist in v1) | Reuses R-001 output (FR-007). |
| `gen_ai.tool.call.result` | — | **OMITTED v1** | — | Not capturable at span boundary (R-005, G-3). |
| `gen_ai.conversation.id` | string | Added (Tier 2) | designed entry point `GH_ADDRESS_CR_CONVERSATION_ID` → else passive fallback `CLAUDE_CODE_SESSION_ID` | Omitted when none present (fail-open). Public-safe (session UUID). R-009/FR-011. |
| `gen_ai.conversation.id.source` | string | Added (Tier 2) | name of the env var used | Audit/provenance; only set with conversation.id. |
| `gen_ai.agent.name` | string | Added (Tier 2) | `AI_AGENT` env | Omitted when absent. Public-safe product string. |
| `vcs.change.id` | string | Added (Tier 1) | PR number from argv | Only for PR-scoped commands; omitted otherwise. FR-012. |
| `vcs.provider.name` | string | Added (Tier 1) | constant `"github"` | Set with `vcs.change.id`. |
| `vcs.repository.name` | string | Added (Tier 1) | **hash** of `owner/repo` (Entity 5) | Opaque, stable per repo. **No plain owner/URL ever** (R-010). |
| `vcs.change.state` | string | Conditional (Tier 1) | session data only, if already present | Omit if not already available; no telemetry-driven GitHub lookup. |
| `service.version`, `cli.entrypoint` | string | existing | already set | Unchanged. |

### Validation rules
- `error.type` appears **iff an exception propagated** (a crash); it MUST NOT
  appear on any non-crash run, including a non-zero **status** exit (F1).
- `process.command_args` and `gen_ai.tool.call.arguments` MUST derive from one
  sanitizer call — no second, differently-filtered copy.
- No attribute may contain a raw token/credential/username/unnecessary abs path
  (enforced by the sanitizer + existing safety helpers).
- **No attribute may contain the plain `owner` name or `vcs.repository.url.full`**
  (Tier 1 privacy). `vcs.repository.name` MUST be the opaque hash only.
- `gen_ai.conversation.id.source` MUST be present iff `gen_ai.conversation.id` is.
- `vcs.*` attributes MUST be absent for non-PR commands (`version`, `doctor`).

## Entity 2 — Sanitized Argument Set (new, transient)

Output of the new `safe_command_args(argv: list[str]) -> list[str]`:
- Per-token redaction: any token matching `_contains_token_marker`,
  `_contains_private_identifier`, or `_looks_like_unnecessary_absolute_path` is
  replaced with `"[redacted]"` (not dropped — preserves argument *position* so
  "which slot was wrong" stays visible).
- `--flag=value` tokens: redact only the `value` half if sensitive; keep `--flag`.
- **Argv source (v1)**: the sanitizer input is the argument vector the CLI
  actually processed — `[sys.argv[0]] + (argv if argv is not None else sys.argv[1:])`
  in `__main__.main(argv)`. This makes the value deterministic under tests that
  call `main([...])` (avoids capturing the test runner's own `sys.argv`).
- System-only flags: **none in v1** (the deferred `--traceparent` flag, G-2, is
  out of scope). The `gen_ai.tool.call.arguments` projection therefore equals the
  full sanitized argv in v1; the "exclude system-only flags" rule (FR-007)
  becomes active only when G-2 lands.

## Entity 3 — Caller Trace Context (new, transient)

The resolved parent context for the span. Pure function (v1 MVP signature):
`resolve_parent_context(environ) -> Context | None`.

Priority order (FR-004) — v1 implements levels 2–4; level 1 is deferred:
1. **`--traceparent` flag** *(DEFERRED — G-2, NOT in v1)*: if present and valid →
   use it, precedence over env; malformed → **fail loud** (FR-010). Not built in v1.
2. **`TRACEPARENT` env** (dormant, G-1): if present and well-formed →
   `TraceContextTextMapPropagator().extract({"traceparent": value})` → remote
   parent context. Malformed/absent → returns `None` (INVALID context, no raise;
   FR-005, fail-open).
3. **`process.parent_pid`** attribute (R-003): always recorded by `__main__` as a
   breadcrumb; does NOT set a parent context (independent of this function).
4. **Root span**: when the function returns `None`, `run_traced` starts a normal
   root span.

Determinism: same `environ` → same returned context. Unit-testable in isolation.

## Entity 4 — Agent Session Context (new, transient — Tier 2)

Pure function `detect_agent_session(environ) -> dict[str, str]`:
- **Conversation-id source** (first match wins, bounded to exactly two entries —
  this is intentionally **not** a growing per-vendor detection list, Principle
  X): (1) `GH_ADDRESS_CR_CONVERSATION_ID` — the **designed, vendor-neutral
  entry point** any agent can set (via skill guidance or manual export); (2)
  `CLAUDE_CODE_SESSION_ID` — a **passive, zero-configuration fallback** used
  only because it is free today for Claude Code. On match, returns
  `{gen_ai.conversation.id: <value>, gen_ai.conversation.id.source: <env name>}`.
  A new agent vendor is onboarded by having it set the designed entry point —
  **not** by adding a new detection branch here.
- **Agent name**: `AI_AGENT` → `gen_ai.agent.name` when present.
- Empty dict when nothing matches (→ attributes omitted, fail-open).
- All returned values pass the public-safe sanitation path before use.

## Entity 5 — VCS Change Context (new, transient — Tier 1)

Pure function `map_vcs_attributes(command, repo, pr_number, session) -> dict[str, str]`:
- Returns `{}` unless `repo` (`owner/repo`) and `pr_number` are both present
  (i.e., a PR-scoped command).
- On a PR command:
  - `vcs.change.id` = `str(pr_number)`, `vcs.provider.name` = `"github"`.
  - `vcs.repository.name` = `repo_hash(owner/repo)` — a deterministic, one-way,
    non-reversible digest (stable across runs; algorithm fixed in impl, not a
    public contract; need not be cryptographic — only stable + collision-resistant
    enough to group per repo).
  - `vcs.change.state` = session-provided state **only if already present**;
    otherwise omitted.
- MUST NOT emit plain `owner` or `vcs.repository.url.full`.
- **Command-args scrub (privacy)**: for a PR-scoped invocation, `__main__`
  redacts the plain `owner/repo` positional token in the sanitized argv to
  `"[redacted]"` before setting `process.command_args` / `gen_ai.tool.call.arguments`,
  so the plain owner/repo reaches no span attribute. (Done in `__main__`, not in
  `safe_command_args`, so the generic sanitizer's contract is unchanged.)

## State transitions
None. One span per process; attributes are set at start (identity, args, parent
context, gen_ai) and at close (exit.code, error.type). No persisted state, no
replay surface.
