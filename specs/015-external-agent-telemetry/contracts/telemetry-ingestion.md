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
- Computes a deterministic event fingerprint hash for each canonical event and uses it for idempotent duplicate detection.
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
- `accepted_fingerprints`
- `duplicate_fingerprints`
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
- Aggregates by event fingerprint so duplicate or overlapping imports do not inflate metrics.

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
- `diagnostics`

### Final-Gate Host Telemetry Hook

```text
GH_ADDRESS_CR_HOST_TELEMETRY_INPUT=<path> gh-address-cr final-gate <owner/repo> <pr_number>
```

Behavior:
- When `GH_ADDRESS_CR_HOST_TELEMETRY_INPUT` is set, final-gate imports that JSONL feed before writing `audit_summary.md` and `efficiency-report.json`.
- `GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE` defaults to `assistant-host`.
- `GH_ADDRESS_CR_HOST_TELEMETRY_FORMAT` defaults to `agent-jsonl`.
- Hook ingestion uses the same normalization, safety, fingerprint, duplicate, and diagnostics contract as `telemetry ingest`.
- Hook failures remain fail-open for final-gate and appear as telemetry diagnostics and coverage labels in final-gate evidence.

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
- Duplicate event fingerprints are ignored or reported as duplicates.
- The runtime computes `event_fingerprint` after canonical normalization; producers may provide `event_id`, but the runtime fingerprint is the authoritative deduplication key.

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

Telemetry damage is fail-open for the core PR review workflow. Review, address,
publish, reply, resolve, and final-gate commands must continue when external
telemetry is missing or corrupted, reporting `runtime-only` or `unavailable`
coverage as appropriate. Telemetry ingest and summary commands remain fail-loud
for telemetry-specific failures.

## Failure Reasons

- `TELEMETRY_IMPORTED`
- `TELEMETRY_PARTIAL`
- `MALFORMED_TELEMETRY`
- `UNSAFE_TELEMETRY_CONTENT`
- `UNSUPPORTED_TELEMETRY_FORMAT`
- `TELEMETRY_INPUT_UNAVAILABLE`
- `AMBIGUOUS_TELEMETRY_SESSION`
- `DUPLICATE_TELEMETRY_IMPORT`
- `TELEMETRY_REPORT_UNAVAILABLE`

Telemetry failures are scoped to telemetry commands by default and must not mutate review item state.
