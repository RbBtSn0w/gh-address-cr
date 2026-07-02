# OpenTelemetry Traces: CLI -> Cloudflare Worker

The CLI exports process-level traces using OTLP/HTTP while keeping the local
PR-scoped audit contract authoritative:

- service name: `gh-address-cr`
- endpoint: `https://telemetry-gateway.hamiltonsnow.workers.dev/v1/traces`
- credentials: none in the CLI; the Worker injects backend credentials

The exporter uses an isolated Requests session and fixed non-secret headers.
It does not inherit ambient OTLP headers, credential providers, proxy
authentication, or `.netrc` credentials from the host environment.

Set `GH_ADDRESS_CR_TELEMETRY_ENVIRONMENT=test` in test runners to publish under
the isolated `gh-address-cr-test` service name. Unset it in production.

Trace export is enabled by default. Disable it before invoking the CLI with
either standard privacy control:

```bash
export DISABLE_TELEMETRY=1
# or
export DO_NOT_TRACK=1
```

The process span includes fixed service version and entrypoint attributes.
Custom spans must not include tokens, raw prompts, usernames, private machine
identifiers, or absolute local paths.

`src/gh_address_cr/__main__.py` initializes tracing and calls
`shutdown_telemetry()` in a `finally` block. This asks the batch processor to
flush before a short-lived CLI process exits, including Python exception and
interrupt paths. The wait is capped at 200 ms; an unavailable gateway cannot
block CLI completion. Exception events include only a sanitized exception type,
not the original message or traceback. Export failures are kept off CLI stderr,
and successful `SystemExit(0)` paths such as `--help` remain successful spans.

The exported trace is observed performance evidence only. It never owns review
state, GitHub mutations, local audit artifacts, or final-gate truth.

## `gh-address-cr.cli` span attributes

Every invocation emits exactly one `gh-address-cr.cli` span (kind `INTERNAL`)
carrying:

- `process.executable.name`, `process.pid`, `process.parent_pid`,
  `process.exit.code` — execution identity and the honest exit code
  (Status-to-Action codes are not treated as errors)
- `error.type` — present only when an exception actually propagated, drawn
  from a bounded set (`keyboard_interrupt`, `timeout`, `_OTHER`)
- `process.command_args`, `gen_ai.tool.call.arguments` — sanitized argv (via
  `safe_command_args(...)`); tokens, credentials, and PR `owner/repo` slots
  become `"[redacted]"` in place, position-preserving, never raw
- `gen_ai.operation.name` (`execute_tool`), `gen_ai.tool.name` — GenAI tool
  vocabulary for the invoked command
- `gen_ai.conversation.id` (+ `.source`), `gen_ai.agent.name` — passive
  session correlation from `GH_ADDRESS_CR_CONVERSATION_ID` (preferred) or
  `CLAUDE_CODE_SESSION_ID` (passive fallback), plus `AI_AGENT`; see the
  Session Correlation section in `SKILL.md`
- `vcs.change.id`, `vcs.provider.name` (`github`), `vcs.repository.name` — for
  PR-scoped commands only; `vcs.repository.name` is a stable one-way hash,
  never the plain `owner/repo` string. Non-PR commands carry no `vcs.*`.

Full enforced contract:
`specs/026-cli-otel-agent-integration/contracts/cli-otel-span-attributes.md`.

## Operation span example

```python
from opentelemetry.trace import Status, StatusCode

from gh_address_cr.telemetry import initialize_telemetry, shutdown_telemetry

tracer = initialize_telemetry()
try:
    with tracer.start_as_current_span("my-task") as span:
        span.set_attribute("cli.argument", "value")
        try:
            run_task()
        except Exception as error:
            span.record_exception(RuntimeError(type(error).__name__))
            span.set_status(Status(StatusCode.ERROR))
            raise
finally:
    shutdown_telemetry()
```

## Official references

- OpenTelemetry OTLP exporter spec: [opentelemetry.io/docs/specs/otel/protocol/exporter/](https://opentelemetry.io/docs/specs/otel/protocol/exporter/)
- OTLP transport spec: [opentelemetry.io/docs/specs/otlp/](https://opentelemetry.io/docs/specs/otlp/)
- Cloudflare Workers secrets: [developers.cloudflare.com/workers/configuration/secrets/](https://developers.cloudflare.com/workers/configuration/secrets/)
