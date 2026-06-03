# Quickstart: External Agent Telemetry Ingestion

## Scenario 1: Repair Runtime-Only Metrics Summary

1. Run a PR session that records runtime telemetry or validation command telemetry.
2. Run:

```bash
gh-address-cr final-gate owner/repo 123
```

Expected:
- final-gate still reports unresolved thread and pending review counts.
- output includes an Agent Efficiency Summary.
- coverage label is `runtime-only` when no external telemetry was imported.
- audit summary includes the same telemetry status.
- structured efficiency report artifact exists.

## Scenario 2: Import Generic Agent Telemetry

Create `agent-telemetry.jsonl`:

```jsonl
{"schema_version":"1.0","source":"generic-agent","source_session_id":"run-1","event_id":"e1","kind":"tool_call","operation":"run unit tests","duration_ms":89105,"status":"success","metadata":{"command_label":"python3 -m unittest discover -s tests","exit_code":0}}
{"schema_version":"1.0","source":"generic-agent","source_session_id":"run-1","event_id":"e2","kind":"tool_call","operation":"lint","duration_ms":450,"status":"success","metadata":{"command_label":"ruff check src tests","exit_code":0}}
```

Run:

```bash
gh-address-cr telemetry ingest owner/repo 123 --source generic-agent --format agent-jsonl --input agent-telemetry.jsonl
gh-address-cr telemetry summary owner/repo 123 --format markdown
```

Expected:
- import reports `accepted_count=2`.
- summary includes source `generic-agent`.
- slowest operations include `run unit tests`.
- coverage label is `complete` or `partial` depending on runtime telemetry availability.

## Scenario 3: Duplicate Import

Run the same ingest command twice.

Expected:
- second import reports duplicates.
- duplicate handling is based on deterministic event fingerprint hashes.
- total event count, observed duration, retry count, and slowest-operation rankings do not change.

## Scenario 4: Unsafe Telemetry Rejection

Create a telemetry feed containing a token-like value or raw prompt content.

Expected:
- import fails with `UNSAFE_TELEMETRY_CONTENT` or records a rejected diagnostic.
- unsafe content is not written to the shareable report.
- existing review session state is unchanged.

## Scenario 5: Final-Gate With External Telemetry

After importing valid external telemetry, run:

```bash
gh-address-cr final-gate owner/repo 123
```

Expected:
- final-gate includes telemetry coverage.
- audit summary includes report artifact metadata.
- final-gate remains authoritative for review-thread and pending-review completion.

## Scenario 6: Corrupted Telemetry Does Not Block Core Workflow

Corrupt or remove the external telemetry artifact after a PR session exists, then run:

```bash
gh-address-cr final-gate owner/repo 123
```

Expected:
- final-gate still evaluates unresolved threads, pending reviews, blocking items, and validation evidence.
- telemetry coverage is reported as `runtime-only` or `unavailable`.
- telemetry diagnostics are visible through telemetry-specific report commands.
- review, address, publish, reply, resolve, and final-gate behavior is not blocked by telemetry damage.
