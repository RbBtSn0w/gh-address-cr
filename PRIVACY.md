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

The CLI exports process-level OpenTelemetry traces by default to the public
Cloudflare Worker at
`https://telemetry-gateway.hamiltonsnow.workers.dev/v1/traces`. The service name
is `gh-address-cr`. The client contains no API key or backend credential.
Ambient OTLP headers, credential providers, proxy credentials, and `.netrc`
credentials are not inherited by the gateway exporter.
When `GH_ADDRESS_CR_TELEMETRY_ENVIRONMENT=test` is set, traces use the isolated
service name `gh-address-cr-test` instead of the production dataset name.

Set either `DISABLE_TELEMETRY=1` or `DO_NOT_TRACK=1` to disable initialization
and network export. Exported CLI spans contain fixed service/version/entrypoint
attributes plus the exception type when the CLI terminates with an exception.
Exception messages and stack traces are not exported.
Raw CLI arguments are not attached to the process span. Custom instrumentation
must not attach tokens, raw prompts, usernames, machine identifiers, or local
paths.

Local audit files remain the authoritative workflow record. Exported traces do
not control review state, GitHub side effects, or final-gate truth.
Exporter failures are suppressed from CLI stderr so telemetry cannot alter
human or machine-readable output contracts.

## OpenAI/Codex Packaging

The Codex skill and plugin packages contain instructions, references, helper
shims, and presentation metadata. They do not include a ChatGPT Apps SDK app,
MCP server, hosted service, or separate OpenAI account integration.
