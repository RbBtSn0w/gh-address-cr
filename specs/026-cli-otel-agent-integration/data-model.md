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
| `process.exit.code` | int | Required | return value of `cli_main` (0 on success); on propagated exception, synthetic `1` | Always present, incl. exception path (R-006, U1). |
| `error.type` | string | Conditional (exit ≠ 0 only) | bounded set: `"nonzero_exit"`, whitelisted expected exception class name, else `_OTHER` | Low-cardinality; **unset on success**; no unbounded class names (A2). |
| `process.command_args` | string[] | Recommended | `safe_command_args([sys.argv[0]] + (argv if argv is not None else sys.argv[1:]))` | Sanitized (R-001). Never raw. Argv source pinned for test determinism (see Entity 2). |
| `process.parent_pid` | int | Opt-In | `os.getppid()` | Fallback breadcrumb only (R-003); **replaces** spec's `system.process.parent_id` (G-5). |
| `gen_ai.operation.name` | string | Added | constant `"execute_tool"` | |
| `gen_ai.tool.name` | string | Added | parsed top-level command (e.g. `review`), else `"gh-address-cr"` | Matches public command surface. |
| `gen_ai.tool.call.arguments` | string (JSON) | Added | JSON of the **same** `safe_command_args` value (no system-only flags exist in v1) | Reuses R-001 output (FR-007). |
| `gen_ai.tool.call.result` | — | **OMITTED v1** | — | Not capturable at span boundary (R-005, G-3). |
| `service.version`, `cli.entrypoint` | string | existing | already set | Unchanged. |

### Validation rules
- `error.type` MUST NOT appear when `process.exit.code == 0`.
- `process.command_args` and `gen_ai.tool.call.arguments` MUST derive from one
  sanitizer call — no second, differently-filtered copy.
- No attribute may contain a raw token/credential/username/unnecessary abs path
  (enforced by the sanitizer + existing safety helpers).

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

## State transitions
None. One span per process; attributes are set at start (identity, args, parent
context, gen_ai) and at close (exit.code, error.type). No persisted state, no
replay surface.
