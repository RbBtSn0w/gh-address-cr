# Quickstart: Validating CLI OTel Instrumentation

Validates the MVP contract in [contracts/cli-otel-span-attributes.md](./contracts/cli-otel-span-attributes.md).
No live gateway needed — tests use an in-memory span exporter.

## Prerequisites
```bash
pip install -e .            # required before tests (test discovery needs the installed package)
```

## 1. Unit / contract tests (primary gate)
In the new `tests/test_cli_otel_execution.py` / `test_cli_otel_context.py` /
`test_cli_otel_genai.py` (plus `test_telemetry_safety_command_args.py` and
`test_otel_semconv_pins.py`), use an in-memory `TracerProvider` +
`InMemorySpanExporter`, run the CLI entrypoint, and assert the exported span.

```bash
python3 -m unittest discover -s tests
```

Expected assertions (map to contract IDs):
- Span `gh-address-cr.cli`, kind `INTERNAL`, count == 1 (C-1).
- `process.executable.name`, `process.pid` present (C-2).
- Success run: `process.exit.code == 0`, no `error.type` (C-3).
- Failure run (non-zero return / raised exception): matching `process.exit.code`,
  low-cardinality `error.type` present (C-3).
- Sensitive-arg run (e.g. a token positional / `--flag=ghp_...`): the value is
  `"[redacted]"` in both `process.command_args` and `gen_ai.tool.call.arguments`;
  no raw secret anywhere on the span (C-4/C-5).
- `gen_ai.operation.name == "execute_tool"`, `gen_ai.tool.name` present,
  `gen_ai.tool.call.result` **absent** (C-5).
- `process.parent_pid` present, span trace id unchanged by it (C-6).
- Malformed `TRACEPARENT` env → root span, unchanged exit code (C-7/C-8).
- Well-formed `TRACEPARENT` env → span parent == injected trace id (C-7 dormant).
- Tier 2: with `CLAUDE_CODE_SESSION_ID` set, two invocations carry an identical
  `gen_ai.conversation.id` (+ `.source`) and `gen_ai.agent.name`; with none set,
  all three absent (C-11).
- Tier 1: a PR-scoped run (`review acme/widgets 123`) has `vcs.change.id=="123"`,
  `vcs.provider.name=="github"`, hashed `vcs.repository.name`, and **no** plain
  `owner`/URL anywhere on the span; a non-PR run (`version`) has no `vcs.*` (C-12).

## 2. Smoke checks
```bash
python3 -m gh_address_cr --help          # CLI still works, no new required flags (SC-005)
DISABLE_TELEMETRY=1 python3 -m gh_address_cr version   # telemetry off path unaffected
```

## 3. Manual dormant-path check (optional, illustrates G-1)
Simulate what an agent *would* do if it propagated context:
```bash
TRACEPARENT="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" \
  python3 -m gh_address_cr version
```
Confirm (via the in-memory exporter test, not the live gateway) the span's parent
trace id equals `0af7651916cd43dd8448eb211c80319c`. In the field this stays
dormant until a real agent injects `TRACEPARENT` (see research.md R-002).

## Out of scope for this guide
- `--traceparent` flag (G-2), `gen_ai.tool.call.result` (G-3): not built until
  confirmed; no validation steps here.
- Live gateway export: covered by existing bounded-export tests; unchanged.
