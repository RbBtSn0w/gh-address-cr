# Contract: CLI OTel Span Attributes

The public/observable contract this feature commits to. Enforced by unittest in the new
`tests/test_cli_otel_*.py`, `tests/test_telemetry_safety_command_args.py`, and
`tests/test_otel_semconv_pins.py` files (in-memory span exporter). "MVP" =
landable subset; "GATED" = requires human confirmation before build.

## C-1 Single span (MVP)
- Exactly one span named `gh-address-cr.cli`, kind `INTERNAL`, per invocation.
- No additional span, tracer, processor, or exporter is introduced.
- The root CLI span MAY carry internal timeline events for command/session
  progress (for example preflight, session, ingest, gate, summary, and
  subprocess markers). These events do not create additional spans and
  preserve the single-span trace shape.
- **Enforced**: a test asserts `len(exported_spans) == 1` and
  `span.kind == SpanKind.INTERNAL` for a representative invocation.

## C-2 Execution identity (MVP)
- Every exported span carries `process.executable.name` (string) and
  `process.pid` (int).

## C-3 Exit outcome (MVP)
- Every exported span carries the honest `process.exit.code` (int). On a normal
  return it equals the CLI's return code; when an exception propagates out of
  `cli_main` it is a **synthetic `1`**.
- The root span applies the generic OTel CLI-spans rule "error iff
  `process.exit.code != 0`" **with one bounded, enumerated exemption**: the
  CLI's own Status-to-Action outcome codes —
  `STATUS_EXIT_CODES = {2=needs-action, 4=needs-human, 5=blocked/preflight,
  6=WAITING_FOR_EXTERNAL_REVIEW}` (defined in `cli.py`, injected into
  `run_traced` via `non_error_exit_codes`) — are **not** errors, because
  marking these deliberate workflow outcomes as failures would inflate failure
  counts (Principle VIII).
- Therefore `error.type` is present **and** span status is ERROR iff either:
  - an exception propagated (a genuine crash), **or**
  - the exit code is non-zero **and not** in `STATUS_EXIT_CODES` (e.g.
    `1`=FAILED/UNKNOWN, or any unrecognized non-zero code) — a genuine failure
    that returns rather than raises.
  `error.type` is absent and span status is unset on success (0) and on every
  exempted status code. *(Narrowed deviation: only the enumerated status
  vocabulary is exempt from the generic rule; genuine failures — including a
  non-raising `return 1` — are honestly reported so failure telemetry stays
  queryable.)*
- `error.type` values are drawn from an **explicitly enumerated bounded set**
  (all literal strings):
  - `"keyboard_interrupt"` — `KeyboardInterrupt` propagated;
  - `"timeout"` — `TimeoutError` propagated;
  - `"_OTHER"` — any other propagated exception **or** a genuine non-zero
    non-exempt exit (the literal string `_OTHER`, the OTel well-known fallback
    value).
  Arbitrary/raw exception class names MUST NOT be passed through (cardinality
  guard, Principle VIII).

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

## C-13 Subprocess caller span — CLI spans "Client (caller)" alignment (MVP)
- The `gh_address_cr.subprocess` child span (wrapping `gh`/other external
  invocations) is span kind `CLIENT`, per the OTel CLI spans "Client (caller)
  spans" convention (distinct from the root span's `INTERNAL` "Execution
  (callee)" kind).
- It carries `process.executable.name` (already present), `process.pid` of
  the spawned child process (sourced from `Popen.pid`, refreshed per retry
  attempt), and `process.exit.code` of the last attempt.
- `error.type` is present **iff** the final `process.exit.code != 0`, **and
  the span status is set to ERROR in exactly the same condition** — this span
  follows the generic OTel "error iff exit≠0" rule for both `error.type` and
  span status (the spec: "An Error is defined as when the `process.exit.code`
  attribute is not 0"), unlike the root span's C-3 deviation, because a
  non-zero exit from an *external* tool is a genuine operational failure, not
  one of gh-address-cr's own Status-to-Action outcome codes. `error.type`
  value is the literal `"timeout"` on a timeout (exit 124), else the
  stringified exit code (bounded cardinality, consistent with the spec's own
  `error.type` example of using an HTTP-status-like string).
- Both `error.type` and span status are set **once, from the final exit
  code**, after all retries. A transient timeout that later succeeds on retry
  leaves the span with `exit.code == 0`, **no** `error.type`, and a non-ERROR
  status (no stale error residue from the timed-out attempt).
- `process.executable.path` is intentionally **not** set on either this span
  or the root span: on this project's target platforms the resolved path
  reliably contains `/Users/<user>/...` or `/home/<user>/...`, which
  `telemetry_safety._looks_like_unnecessary_absolute_path` already treats as
  unsafe. Emitting it would leak local usernames. Since the attribute is
  Recommended (not Required) in the spec, it is omitted rather than sanitized
  down to a value that duplicates `process.executable.name`.
- **Enforced**: `tests/test_command_runner_otel_span.py` (in-memory span
  exporter) asserts CLIENT kind, `process.pid` presence, and `error.type` +
  span-status (ERROR/non-ERROR) across success, non-zero exit, timeout, and
  the transient-timeout-then-success (no-residue) case.

## GATED contracts (NOT built until confirmed)
- **C-9 (G-2) `--traceparent`**: a global public flag accepting a full W3C
  traceparent string; when valid it is used for correlation with precedence over
  the `TRACEPARENT` env; a malformed value **fails loud** (as CLI arg validation,
  not a telemetry failure). Requires public CLI contract versioning + a skill
  instruction so the agent actually passes it.
- **C-10 (G-3) `gen_ai.tool.call.result`**: low-cardinality structured summary
  fields (e.g. `status`, `reason_code`), truncated; requires CLI-internal
  plumbing. Never raw stdout.
- **(G-4) `process.executable.path` / install-channel signal**: the raw
  semconv attribute is **not** implemented on either span (root or
  subprocess). On this project's target platforms the resolved path reliably
  contains `/Users/<user>/...` or `/home/<user>/...` (or, for CI-run
  binaries, may embed `owner/repo` — which C-12 already goes out of its way
  to hash), so emitting it verbatim would leak identifying context that a
  `~`-substitution or other partial mask cannot fully close (arbitrary
  directory-tree segments, e.g. `~/clients/<confidential-project>/...`,
  remain unenumerable). There is currently no concrete, evidenced debugging
  need for this signal. If one materializes (e.g. bug reports traceable to a
  specific install channel), the correct design is a new project-namespaced
  bounded enum — e.g. `gh_address_cr.install_channel ∈ {pipx, homebrew,
  venv, source_checkout, system, unknown}` derived locally from
  `sys.executable`/`__file__` — never the raw path, and never a value stored
  under the `process.executable.path` key itself (repurposing an official
  semconv key for a non-literal value would mislead consumers). See
  `AGENTS.md` § Telemetry for the general "derive a signal, don't sanitize a
  string" principle this follows.

## Verification
`python3 -m unittest discover -s tests` (new files
`tests/test_cli_otel_execution.py`, `tests/test_cli_otel_context.py`,
`tests/test_cli_otel_genai.py`, `tests/test_telemetry_safety_command_args.py`,
`tests/test_otel_semconv_pins.py`, `tests/test_command_runner_otel_span.py`) +
smoke `python3 -m gh_address_cr --help`. See [quickstart.md](../quickstart.md).
