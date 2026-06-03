# Data Model: External Agent Telemetry Ingestion

## ExternalTelemetryEvent

Represents one observed event from an external agent host or the runtime.

Fields:
- `schema_version`: version of the event contract.
- `source`: source label such as `runtime`, `generic-agent`, `codex`, or another host identifier.
- `source_session_id`: identifier for the source agent session or run.
- `event_id`: source-provided or runtime-derived stable event identifier.
- `kind`: event category such as `tool_call`, `command`, `wait`, `retry`, `validation`, or `agent_step`.
- `operation`: public-safe operation label.
- `started_at`: event start timestamp when available.
- `ended_at`: event end timestamp when available.
- `duration_ms`: observed duration when direct timestamps are unavailable.
- `status`: `success`, `failure`, `timeout`, `cancelled`, or `unknown`.
- `metadata`: sanitized optional key/value context.
- `correlation_id`: optional id that links external events to runtime validation or command records.
- `event_fingerprint`: deterministic hash generated after canonical normalization from source, source session identity, event id when present, kind, operation, timing, status, and correlation id when present.

Validation rules:
- `source`, `kind`, `operation`, and `status` are required.
- At least one of `duration_ms` or both `started_at` and `ended_at` is required for timing-based reporting.
- Unsafe metadata is rejected or sanitized before storage.
- Duplicate `event_fingerprint` values do not create additional report events, even when overlapping imported logs use different source-provided event ids.
- When `event_id` is absent, the fingerprint must still be stable for repeated imports of the same canonical event.

## TelemetryImport

Represents one PR-scoped ingestion attempt.

Fields:
- `import_id`: stable identifier for the ingestion attempt.
- `repo`: repository name.
- `pr_number`: pull request number.
- `source`: declared telemetry source.
- `format`: input format label.
- `status`: `accepted`, `partial`, `rejected`, or `duplicate`.
- `accepted_count`: number of accepted events.
- `rejected_count`: number of rejected events.
- `duplicate_count`: number of duplicate events.
- `accepted_fingerprints`: event fingerprints accepted by the import.
- `duplicate_fingerprints`: event fingerprints rejected as already seen.
- `diagnostics`: actionable messages for rejected or sanitized records.
- `created_at`: import timestamp.

State transitions:
- `received` -> `accepted` when all valid records are stored.
- `received` -> `partial` when some records are accepted and some rejected.
- `received` -> `rejected` when no records can be accepted.
- `received` -> `duplicate` when all records were already imported.
- Telemetry import failures do not transition or mutate review item state.

## TelemetrySource

Describes one observation surface represented in a report.

Fields:
- `source`: source label.
- `source_type`: `runtime`, `generic-agent`, `host-adapter`, or `manual`.
- `coverage_status`: `available`, `partial`, `missing`, or `unavailable`.
- `event_count`: accepted event count from this source.
- `notes`: user-safe explanation of coverage limitations.

## CoverageReport

Explains how complete the telemetry evidence is.

Fields:
- `coverage_label`: `complete`, `partial`, `runtime-only`, or `unavailable`.
- `sources`: list of `TelemetrySource` entries.
- `missing_sources`: expected but absent observation surfaces.
- `confidence`: `high`, `medium`, or `low`.
- `summary`: user-facing explanation of what was observed.

## EfficiencyReport

Combines runtime and external telemetry into a shareable workflow efficiency summary.

Fields:
- `repo`: repository name.
- `pr_number`: pull request number.
- `coverage`: `CoverageReport`.
- `total_events`: total accepted report events.
- `success_rate`: percentage of successful events with known status.
- `total_observed_duration_ms`: sum of non-duplicated observed durations.
- `slowest_operations`: top slow operations with source attribution.
- `error_prone_operations`: operation groups with failures, retries, or timeouts.
- `inefficiency_flags`: human-readable optimization signals.
- `report_generated_at`: timestamp.
- `report_artifact`: path or identifier for the structured report.

Validation rules:
- Reports must include a coverage label even when no events are available.
- Runtime-only reports are valid and must be explicit.
- Reports must not expose unsafe metadata.
- Reports must aggregate by event fingerprint so duplicate or overlapping imports do not inflate counts, durations, retry counts, or slowest-operation rankings.
- Damaged or unreadable external telemetry must fail loudly for telemetry report requests or be represented as `unavailable` coverage without blocking core PR review workflows.
