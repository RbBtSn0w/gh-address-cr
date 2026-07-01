# Contract: CLI OTel Span Attributes

The public/observable contract this feature commits to. Enforced by unittest in the new
`tests/test_cli_otel_*.py`, `tests/test_telemetry_safety_command_args.py`, and
`tests/test_otel_semconv_pins.py` files (in-memory span exporter). "MVP" =
landable subset; "GATED" = requires human confirmation before build.

## C-1 Single span (MVP)
- Exactly one span named `gh-address-cr.cli`, kind `INTERNAL`, per invocation.
- No additional span, tracer, processor, or exporter is introduced.
- **Enforced**: a test asserts `len(exported_spans) == 1` and
  `span.kind == SpanKind.INTERNAL` for a representative invocation.

## C-2 Execution identity (MVP)
- Every exported span carries `process.executable.name` (string) and
  `process.pid` (int).

## C-3 Exit outcome (MVP)
- Every exported span carries `process.exit.code` (int). On a normal return it
  equals the CLI's return code; when an exception propagates out of `cli_main`
  it is a **synthetic non-zero code (`1`)** so exit.code is always present.
- `error.type` (string, low-cardinality) is present **iff** `process.exit.code != 0`
  or an exception propagated. It MUST be absent on exit code 0.
- `error.type` values are drawn from an **explicitly enumerated bounded set**:
  - `"nonzero_exit"` — non-zero return with no exception;
  - `"keyboard_interrupt"` — `KeyboardInterrupt` propagated;
  - `"timeout"` — `TimeoutError` propagated;
  - `_OTHER` — any other propagated exception.
  The whitelist is intentionally minimal and extended only with evidence of a
  new predictable, low-cardinality failure class. Arbitrary/raw exception class
  names MUST NOT be passed through (cardinality guard, Principle VIII).

## C-4 Sanitized arguments (MVP)
- `process.command_args` (string[]) is present and is the output of
  `safe_command_args(...)` over the **argv the CLI actually processed** —
  `[sys.argv[0]] + (argv if argv is not None else sys.argv[1:])` — not raw
  `sys.argv` (deterministic under `main([...])` tests; see data-model Entity 2).
- No span attribute contains a raw token/credential/username/unnecessary absolute
  path. Test includes at least one invocation with deliberately sensitive input
  and asserts redaction to `"[redacted]"`.
- Redaction preserves argument **position** (redacted placeholder, not removal).

## C-5 GenAI tool vocabulary (MVP)
- `gen_ai.operation.name == "execute_tool"`.
- `gen_ai.tool.name` is present (parsed command name, else `"gh-address-cr"`).
- `gen_ai.tool.call.arguments` (JSON string) derives from the **same** sanitized
  value as C-4: `json.loads(arguments)` MUST equal the `process.command_args`
  list. No independently-filtered copy. *(No system-only flags exist in v1, so
  the "exclude system-only flags" clause of FR-007 is vacuous until G-2 lands.)*
- `gen_ai.tool.call.result` is **absent** in v1 (documented omission, G-3).

## C-6 Parent-pid breadcrumb (MVP)
- `process.parent_pid` (int) is present, sourced from `os.getppid()`.
- It does NOT alter the span's trace/span ids.

## C-7 Context linking — fail-open (MVP behavior for dormant path)
- Given a well-formed `TRACEPARENT` env value, the span is a child of that remote
  context. *(Dormant: exercised only when a caller injects it — G-1.)*
- Given a missing or malformed `TRACEPARENT`, the CLI completes normally as a root
  span; exit code and functional behavior are unchanged. A broken header never
  blocks, hangs, or fails the command.

## C-8 Telemetry never changes CLI behavior (MVP)
- For all inputs above (including malformed context/sensitive args), the CLI's
  exit code equals what it would be with telemetry disabled
  (`DISABLE_TELEMETRY=1`). Telemetry-layer failures are fail-open.

## GATED contracts (NOT built until confirmed)
- **C-9 (G-2) `--traceparent`**: a global public flag accepting a full W3C
  traceparent string; when valid it is used for correlation with precedence over
  the `TRACEPARENT` env; a malformed value **fails loud** (as CLI arg validation,
  not a telemetry failure). Requires public CLI contract versioning + a skill
  instruction so the agent actually passes it.
- **C-10 (G-3) `gen_ai.tool.call.result`**: low-cardinality structured summary
  fields (e.g. `status`, `reason_code`), truncated; requires CLI-internal
  plumbing. Never raw stdout.

## Verification
`python3 -m unittest discover -s tests` (new files
`tests/test_cli_otel_execution.py`, `tests/test_cli_otel_context.py`,
`tests/test_cli_otel_genai.py`, `tests/test_telemetry_safety_command_args.py`,
`tests/test_otel_semconv_pins.py`) +
smoke `python3 -m gh_address_cr --help`. See [quickstart.md](../quickstart.md).
