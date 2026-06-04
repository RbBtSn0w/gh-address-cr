# Feature Spec: Host-Specific Telemetry Adapters

## Summary

Add host-specific telemetry adapters after the generic registry boundary, starting with safe aggregate Codex host exports.

## Behavior

- `--source codex --format codex-host-json` normalizes turns and tool calls into `ExternalTelemetryEvent`.
- Aggregate token counts and tool-call counts may appear in structured efficiency reports.
- Existing safety filters, fingerprinting, deduplication, coverage labels, and fail-open/fail-loud behavior still apply.
- Host adapters are optional enrichment over `agent-jsonl`.

## Owner Boundary

Telemetry adapter registration, normalization, and report aggregation live in runtime telemetry code.

## Verification

- `python3 -m unittest tests.test_issue78_agent_experience.Issue78TelemetryAdapterTests`
- `python3 -m unittest tests.core.test_telemetry`
- `ruff check src tests`
- `python3 -m unittest discover -s tests`
- `python3 -m gh_address_cr --help`
