"""Host telemetry auto-capture: native session log -> agent-jsonl text.

Output is fed to core.telemetry.import_external_telemetry; this package never
touches the ingest/normalize/redact/fingerprint pipeline directly.
"""
