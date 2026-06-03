# Contract: Telemetry Ingestion And Reporting

## Public Command Surface

### Import Generic Telemetry

```text
gh-address-cr telemetry ingest <owner/repo> <pr_number> --source <source> --format agent-jsonl --input <path>|-
```

Behavior:
- Accepts a PR-scoped external telemetry feed.
- Normalizes accepted events into the runtime telemetry store.
- Fails loudly for malformed or unsafe feeds without changing review item state.
- Returns a machine-readable import summary.

Required machine fields:
- `status`
- `reason_code`
- `repo`
- `pr_number`
- `source`
- `format`
- `accepted_count`
- `rejected_count`
- `duplicate_count`
- `diagnostics`
- `next_action`

### Generate Telemetry Summary

```text
gh-address-cr telemetry summary <owner/repo> <pr_number> [--format json|markdown]
```

Behavior:
- Combines runtime telemetry and imported external telemetry.
- Emits coverage label and report metadata.
- Does not mutate review item state.

Required machine fields:
- `status`
- `reason_code`
- `repo`
- `pr_number`
- `coverage_label`
- `sources`
- `total_events`
- `success_rate`
- `total_observed_duration_ms`
- `slowest_operations`
- `error_prone_operations`
- `inefficiency_flags`
- `report_artifact`

## Generic Agent Event Feed

Each line is one JSON event.

```json
{
  "schema_version": "1.0",
  "source": "generic-agent",
  "source_session_id": "session-123",
  "event_id": "event-001",
  "kind": "tool_call",
  "operation": "run unit tests",
  "started_at": "2026-06-03T06:00:00Z",
  "ended_at": "2026-06-03T06:01:29Z",
  "status": "success",
  "metadata": {
    "command_label": "python3 -m unittest discover -s tests",
    "exit_code": 0
  }
}
```

Rules:
- `source`, `kind`, `operation`, and `status` are required.
- `duration_ms` may replace `started_at` plus `ended_at`.
- Metadata must be public-safe.
- Unknown metadata keys may be preserved only if safe.
- Duplicate event identities are ignored or reported as duplicates.

## Coverage Labels

- `complete`: runtime telemetry and expected host telemetry are both present.
- `partial`: some external telemetry was imported, but expected observation surfaces are missing or incomplete.
- `runtime-only`: runtime telemetry is present, but no external host telemetry was imported.
- `unavailable`: no usable telemetry is available.

## Final-Gate Integration

Final-gate output and `audit_summary.md` must include:
- coverage label
- source summary
- report artifact identifier or path
- top inefficiency signals
- telemetry diagnostics when imports were rejected or partial

Existing final-gate counts and reason codes remain stable.

## Failure Reasons

- `MALFORMED_TELEMETRY`
- `UNSAFE_TELEMETRY_CONTENT`
- `UNSUPPORTED_TELEMETRY_FORMAT`
- `AMBIGUOUS_TELEMETRY_SESSION`
- `DUPLICATE_TELEMETRY_IMPORT`
- `TELEMETRY_REPORT_UNAVAILABLE`

Telemetry failures are scoped to telemetry commands by default and must not mutate review item state.
