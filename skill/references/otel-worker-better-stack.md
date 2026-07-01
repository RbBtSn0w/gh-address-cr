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

The process span includes fixed service version and entrypoint attributes. Raw
CLI arguments are not attached. Custom spans must not include tokens, raw
prompts, usernames, private machine identifiers, or absolute local paths.

`src/gh_address_cr/__main__.py` initializes tracing and calls
`shutdown_telemetry()` in a `finally` block. This asks the batch processor to
flush before a short-lived CLI process exits, including Python exception and
interrupt paths. The wait is capped at 200 ms; an unavailable gateway cannot
block CLI completion. Exception events include only a sanitized exception type,
not the original message or traceback. Export failures are kept off CLI stderr,
and successful `SystemExit(0)` paths such as `--help` remain successful spans.

The exported trace is observed performance evidence only. It never owns review
state, GitHub mutations, local audit artifacts, or final-gate truth.

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
