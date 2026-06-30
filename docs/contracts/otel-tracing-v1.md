# Contract: `otel-tracing.v1`

## Scope And Ownership

The process-level OpenTelemetry trace is an additive CLI observability
contract. The **Process-level observability owner** is
`src/gh_address_cr/telemetry.py`; `src/gh_address_cr/__main__.py` owns its CLI
lifecycle integration.

This contract does not belong to the read-only evaluation plane in
`specs/023-runtime-eval-foundation/`. It is also separate from PR-scoped
workflow telemetry in `src/gh_address_cr/core/telemetry.py`. Exported spans are
never runtime events, evaluation inputs, final-gate evidence, or local audit
artifacts.

## Architecture Preflight

### External inputs

- CLI process start and completion
- successful or non-successful `SystemExit`
- sanitized exception type
- `DISABLE_TELEMETRY=1` and `DO_NOT_TRACK=1`
- `GH_ADDRESS_CR_TELEMETRY_ENVIRONMENT=test`

Raw CLI arguments, exception messages, tracebacks, prompts, credentials,
usernames, machine identifiers, and local paths are outside the accepted input
contract.

### Span projection

The provider derives one process span named `gh-address-cr.cli` with fixed
entrypoint and service-version attributes. `service.name` is `gh-address-cr` in
production and `gh-address-cr-test` in the explicit test environment. A normal
`SystemExit(0)` is successful; non-zero exits and exceptions set Error status
using only a sanitized exception type.

### Export policy

- protocol: OTLP/HTTP traces
- endpoint: `https://telemetry-gateway.hamiltonsnow.workers.dev/v1/traces`
- client credentials: none
- ambient OTLP headers and credential providers: ignored
- Requests environment, proxy credentials, and `.netrc`: ignored
- exporter timeout: 150 ms
- maximum shutdown join: 200 ms
- opt-out: either supported privacy variable returns a no-op tracer

### Side-effect boundary

`OTLPSpanExporter` is the only network side effect. The Cloudflare Worker owns
backend credential injection. Export failures are fail-open, stay off CLI
stdout/stderr, and cannot change command output, exit status, runtime state,
GitHub state, or final-gate results.

### Artifact truth boundary

No exported span or remote telemetry dataset is authoritative repository truth.
The exporter does not write local runtime artifacts. PR-scoped audit,
efficiency, evaluation, and final-gate artifacts retain their existing owners
and contracts.

### Recovery and replay

Shutdown attempts one bounded flush. A blocked or failed exporter may drop the
span after the budget expires; it must never delay or fail the CLI. There is no
retry ledger or replay into runtime/evaluation state. Re-running a command
creates a new observation and cannot satisfy previous workflow evidence.

## Compatibility And Versioning

The following are public `otel-tracing.v1` behavior: default enablement,
opt-out variables, service names, endpoint, privacy exclusions, fail-open
output behavior, and bounded shutdown. A breaking change to these fields or
semantics requires a new contract version plus synchronized implementation,
documentation, and executable tests.

