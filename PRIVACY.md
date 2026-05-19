# Privacy Policy

`gh-address-cr` is a local CLI runtime plus Codex skill/plugin package for
pull request review-resolution workflows.

## Data Sources

The runtime uses the local GitHub CLI (`gh`) and the GitHub authentication that
is already available on the user's machine or CI runner. It may read pull
request metadata, review threads, pending reviews, check status, repository
paths, review comments, and local normalized findings supplied by an external
review producer.

## Local State

The runtime writes PR-scoped local state under `GH_ADDRESS_CR_STATE_DIR` when it
is set, otherwise under the user's cache directory. Local state can include:

- `session.json`
- `audit.jsonl`
- `trace.jsonl`
- generated reply drafts
- action request and response artifacts
- `audit_summary.md`

These files are the canonical audit record for the workflow.

## GitHub Side Effects

`gh-address-cr` can perform GitHub side effects only through explicit runtime
commands. Those side effects may include posting review-thread replies and
resolving review threads. Agents using the skill/plugin are instructed not to
post replies or resolve threads directly.

## Telemetry

Telemetry is opt-in. By default, the runtime writes only local audit and trace
files and does not export telemetry over the network.

Network telemetry export is enabled only when the user sets
`GH_ADDRESS_CR_TELEMETRY=1` for the hosted relay or configures an explicit
OpenTelemetry endpoint such as `OTEL_EXPORTER_OTLP_ENDPOINT` or
`OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`.

Telemetry payloads are sanitized before export to reduce accidental exposure of
tokens, email addresses, and absolute local paths. Local audit files remain the
authoritative record even when telemetry export is enabled or fails.

## OpenAI/Codex Packaging

The Codex skill and plugin packages contain instructions, references, helper
shims, and presentation metadata. They do not include a ChatGPT Apps SDK app,
MCP server, hosted service, or separate OpenAI account integration.
