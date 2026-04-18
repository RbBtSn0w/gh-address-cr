# Optional Telemetry Export: CLI -> Cloudflare Worker -> Better Stack

This skill keeps the local PR-scoped audit contract intact:

- `audit.jsonl`
- `trace.jsonl`
- `audit_summary.md`

The distributed CLI now ships with a zero-config public relay endpoint:

- `https://gh-address-cr.hamiltonsnow.workers.dev/v1/logs`

By default, each audit/trace event is also exported as an OTLP/HTTP JSON log record to that Cloudflare Worker. The Worker injects the Better Stack source token and forwards the payload to Better Stack `/v1/logs`.

This keeps the Better Stack token out of the CLI runtime.

## Why this shape

- local audit files remain the canonical repo contract
- Better Stack credentials stay in Worker secrets
- end users do not need to configure telemetry before first use
- the implementation stays dependency-light and works with the existing Python-first packaging model

## Signal boundary

Current implementation exports the OpenTelemetry `logs` signal only.

- CLI export target: `POST <worker>/v1/logs`
- transport: `OTLP/HTTP JSON`
- compression: `gzip`

The Worker example in `references/otel-worker-better-stack/worker.mjs` forwards only `/v1/logs`.

## Default CLI behavior

No telemetry environment variables are required for the hosted relay path.

The CLI will export logs to:

```text
https://gh-address-cr.hamiltonsnow.workers.dev/v1/logs
```

## Optional self-host override

If you want to run your own Worker instead of the hosted relay, use standard OpenTelemetry environment variables:

```bash
export OTEL_SERVICE_NAME="gh-address-cr-cli"
export OTEL_RESOURCE_ATTRIBUTES="deployment.environment=personal,service.namespace=skills"
export OTEL_EXPORTER_OTLP_ENDPOINT="https://gh-address-cr-telemetry.example.workers.dev"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/json"
```

Notes:

- `OTEL_EXPORTER_OTLP_ENDPOINT` is treated as a base URL and the CLI appends `/v1/logs`
- alternatively, set `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` to use an exact logs endpoint as-is
- if export fails, the CLI keeps local audit files and appends a local `telemetry_export` diagnostic entry to `trace.jsonl`

## Worker setup

Use the example files:

- Worker code: `references/otel-worker-better-stack/worker.mjs`
- Wrangler example: `references/otel-worker-better-stack/wrangler.example.jsonc`

Recommended bindings:

- secret: `SOURCE_TOKEN`
- var or secret: `INGESTING_HOST`

Example commands:

```bash
wrangler secret put SOURCE_TOKEN
wrangler deploy
```

## Better Stack setup

1. Create a Telemetry source for logs.
2. Copy the source token and ingesting host.
3. Store the source token only in the Worker secret `SOURCE_TOKEN`.
4. Put the ingesting host in `INGESTING_HOST`.

The CLI should never receive the Better Stack source token in this deployment model.

## Quick verification

1. Deploy the Worker.
2. Either use the built-in hosted relay, or export the override env vars above for your own Worker.
3. Run any command that writes audit/trace events, for example:

```bash
python3 scripts/cli.py final-gate owner/repo 123
```

4. Confirm:
   - local `audit.jsonl` and `trace.jsonl` still exist
   - Better Stack receives logs from service `gh-address-cr-cli`
   - no Better Stack token exists in the CLI shell environment

## Official references

- OpenTelemetry OTLP exporter spec: [opentelemetry.io/docs/specs/otel/protocol/exporter/](https://opentelemetry.io/docs/specs/otel/protocol/exporter/)
- OTLP transport spec: [opentelemetry.io/docs/specs/otlp/](https://opentelemetry.io/docs/specs/otlp/)
- Cloudflare Workers secrets: [developers.cloudflare.com/workers/configuration/secrets/](https://developers.cloudflare.com/workers/configuration/secrets/)
- Better Stack OpenTelemetry logging: [betterstack.com/docs/logs/open-telemetry/](https://betterstack.com/docs/logs/open-telemetry/)
