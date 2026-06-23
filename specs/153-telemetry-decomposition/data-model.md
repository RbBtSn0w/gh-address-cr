# Data Model: Telemetry Decomposition

The data model for telemetry remains consistent with the existing implementation, but the ownership of the model classes and their serialization logic is moved to appropriate modules.

## Entities

### ExecutionMetric (Moved to `telemetry_session.py`)
Represents a single timed operation (runtime or external).
- `command`: str
- `start_time`: float
- `end_time`: float
- `exit_code`: int
- `duration`: property (end - start)

### ExternalTelemetryEvent (Moved to `telemetry_attribution.py`)
The normalized internal representation of a telemetry event.
- `source`: str
- `operation`: str
- `timestamp`: str (ISO)
- `duration_ms`: int
- `metadata`: dict
- `fingerprint`: str (calculated via attribution logic)

### EfficiencyReport (Moved to `telemetry_session.py`)
The aggregate summary of a PR session.
- `total_invocations`: int
- `total_duration`: float
- `success_rate`: float
- `coverage_label`: str

## Storage Artifacts (Unchanged)

- `telemetry-imports.jsonl`: Record of import actions.
- `external-telemetry.jsonl`: Normalized external events.
- `telemetry-fingerprints.json`: Set of seen fingerprints to prevent duplicates.
