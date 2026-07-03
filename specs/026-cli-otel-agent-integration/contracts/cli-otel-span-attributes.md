# Contract: CLI OTel Span Attributes

The public/observable contract this feature commits to. Enforced by unittest in the new
`tests/test_cli_otel_*.py`, `tests/test_telemetry_safety_command_args.py`, and
`tests/test_otel_semconv_pins.py` files (in-memory span exporter). "MVP" =
landable subset; "GATED" = requires human confirmation before build.

## C-1 Single span (MVP)
- Exactly one span named `gh-address-cr.cli`, kind `INTERNAL`, per invocation.
- No additional span, tracer, processor, or exporter is introduced.
- The root CLI span MAY carry internal phase events for command/session
  progress (for example preflight, session, ingest, gate, summary, and
  subprocess markers). Events do not create additional spans and preserve the
  single-span trace shape.
- **Enforced**: a test asserts `len(exported_spans) == 1` and
  `span.kind == SpanKind.INTERNAL` for a representative invocation.

## C-2 Execution identity (MVP)
- Every exported span carries `process.executable.name` (string) and
  `process.pid` (int).

## C-3 Exit outcome (MVP)
- Every exported span carries the honest `process.exit.code` (int). On a normal
  return it equals the CLI's return code (including non-zero **status** codes
  like 6=`WAITING_FOR_EXTERNAL_REVIEW`, 2=needs-action, 5=preflight); when an
  exception propagates out of `cli_main` it is a **synthetic `1`**.
- `error.type` is present **iff an exception propagated** (a genuine crash). A
  non-zero *return* by itself MUST NOT set `error.type` — those are Status-to-
  Action outcome codes, and marking them errors would inflate failure counts
  (Principle VIII). `error.type` MUST be absent on every non-crash run
  (success **or** non-zero status). Span status is ERROR only on a propagated
  exception. *(Documented deviation from the generic OTel "error iff exit≠0"
  rule; here an error = a crash.)*
- `error.type` values are drawn from an **explicitly enumerated bounded set**
  (all literal strings):
  - `"keyboard_interrupt"` — `KeyboardInterrupt` propagated;
  - `"timeout"` — `TimeoutError` propagated;
  - `"_OTHER"` — any other propagated exception (the literal string `_OTHER`,
    the OTel well-known fallback value).
  Arbitrary/raw exception class names MUST NOT be passed through (cardinality
  guard, Principle VIII). *(No `"nonzero_exit"` value: a non-zero return is not
  an error.)*

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

## C-11 Passive agent-session correlation (MVP — Tier 2)
- Given a host env session id (`CLAUDE_CODE_SESSION_ID`, else
  `GH_ADDRESS_CR_CONVERSATION_ID`), the span carries `gen_ai.conversation.id`
  equal to that value plus `gen_ai.conversation.id.source` naming the env var,
  and `gen_ai.agent.name` from `AI_AGENT` when present.
- **Enforced**: two invocations under the same session env carry an **identical**
  `gen_ai.conversation.id` (groupable). When no known env is present, all three
  attributes are **absent** (fail-open); the CLI needs no flag and no skill change.
- Recorded values pass the public-safe sanitation path.

## C-12 VCS GitHub-PR mapping + privacy (MVP — Tier 1)
- For a PR-scoped command (`owner/repo <pr>`), the span carries `vcs.change.id`
  (the PR number) and `vcs.provider.name == "github"` in plain text, and
  `vcs.repository.name` as a **stable one-way hash** of `owner/repo` (same repo →
  same value across runs).
- `vcs.change.state` is present **only** when already available in session data;
  otherwise absent (no telemetry-driven GitHub lookup).
- For non-PR commands (`version`, `doctor`), **all `vcs.*` are absent**.
- For a PR-scoped run the plain `owner/repo` token is redacted from
  `process.command_args` and `gen_ai.tool.call.arguments` (`"[redacted]"`,
  position-preserving), so the plain owner/repo appears in **no** attribute.
- **Enforced (privacy)**: a test asserts no span attribute contains the plain
  `owner`/`repo` string or `vcs.repository.url.full` across a sampled PR run,
  while `command_args` still shows the command + PR number + redacted repo slot.

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
